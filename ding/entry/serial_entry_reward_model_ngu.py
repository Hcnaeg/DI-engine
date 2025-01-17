import logging
import os
from functools import partial
from typing import Union, Optional, List, Any, Tuple
import torch
from tensorboardX import SummaryWriter

from ding.config import read_config, compile_config
from ding.envs import get_vec_env_setting, create_env_manager
from ding.policy import create_policy, PolicyFactory
from ding.reward_model import create_reward_model
from ding.reward_model.ngu_reward_model import fusion_reward
from ding.utils import set_pkg_seed
# from ding.worker import BaseLearner, SampleCollector, BaseSerialEvaluator, BaseSerialCommander, create_buffer, \
#     create_serial_collector
from ding.worker import BaseLearner, BaseSerialCommander, create_buffer, create_serial_collector
from ding.worker.collector.base_serial_evaluator_ngu import BaseSerialEvaluatorNGU as BaseSerialEvaluator  # TODO
import copy
from .utils import random_collect


def serial_pipeline_reward_model_ngu(
        input_cfg: Union[str, Tuple[dict, dict]],
        seed: int = 0,
        env_setting: Optional[List[Any]] = None,
        model: Optional[torch.nn.Module] = None,
        max_iterations: Optional[int] = int(1e10),
) -> 'Policy':  # noqa
    """
    Overview:
        Serial pipeline entry with reward model.
    Arguments:
        - input_cfg (:obj:`Union[str, Tuple[dict, dict]]`): Config in dict type. \
            ``str`` type means config file path. \
            ``Tuple[dict, dict]`` type means [user_config, create_cfg].
        - seed (:obj:`int`): Random seed.
        - env_setting (:obj:`Optional[List[Any]]`): A list with 3 elements: \
            ``BaseEnv`` subclass, collector env config, and evaluator env config.
        - model (:obj:`Optional[torch.nn.Module]`): Instance of torch.nn.Module.
        - max_iterations (:obj:`Optional[torch.nn.Module]`): Learner's max iteration. Pipeline will stop \
            when reaching this iteration.
    Returns:
        - policy (:obj:`Policy`): Converged policy.
    """
    if isinstance(input_cfg, str):
        cfg, create_cfg = read_config(input_cfg)
    else:
        cfg, create_cfg = input_cfg
    create_cfg.policy.type = create_cfg.policy.type + '_command'
    env_fn = None if env_setting is None else env_setting[0]
    cfg = compile_config(cfg, seed=seed, env=env_fn, auto=True, create_cfg=create_cfg, save_cfg=True)
    # Create main components: env, policy
    if env_setting is None:
        env_fn, collector_env_cfg, evaluator_env_cfg = get_vec_env_setting(cfg.env)
    else:
        env_fn, collector_env_cfg, evaluator_env_cfg = env_setting
    collector_env = create_env_manager(cfg.env.manager, [partial(env_fn, cfg=c) for c in collector_env_cfg])
    evaluator_env = create_env_manager(cfg.env.manager, [partial(env_fn, cfg=c) for c in evaluator_env_cfg])
    # evaluator_env.enable_save_replay(cfg.env.replay_path)  # switch save replay interface TODO

    collector_env.seed(cfg.seed)
    evaluator_env.seed(cfg.seed, dynamic_seed=False)
    set_pkg_seed(cfg.seed, use_cuda=cfg.policy.cuda)
    policy = create_policy(cfg.policy, model=model, enable_field=['learn', 'collect', 'eval', 'command'])

    # Create worker components: learner, collector, evaluator, replay buffer, commander.
    tb_logger = SummaryWriter(os.path.join('./{}/log/'.format(cfg.exp_name), 'serial'))
    learner = BaseLearner(cfg.policy.learn.learner, policy.learn_mode, tb_logger, exp_name=cfg.exp_name)
    cfg.policy.collect.collector['type'] = 'sample_ngu'
    collector = create_serial_collector(
        cfg.policy.collect.collector,
        env=collector_env,
        policy=policy.collect_mode,
        tb_logger=tb_logger,
        exp_name=cfg.exp_name
    )
    evaluator = BaseSerialEvaluator(
        cfg.policy.eval.evaluator, evaluator_env, policy.eval_mode, tb_logger, exp_name=cfg.exp_name
    )
    replay_buffer = create_buffer(cfg.policy.other.replay_buffer, tb_logger=tb_logger, exp_name=cfg.exp_name)
    commander = BaseSerialCommander(
        cfg.policy.other.commander, learner, collector, evaluator, replay_buffer, policy.command_mode
    )
    # reward_model = create_reward_model(cfg.reward_model, policy.collect_mode.get_attribute('device'), tb_logger)
    # cfg.rnd_reward_model.update({'type':'rnd'})
    # cfg.episodic_reward_model.update({'type':'episodic'})
    rnd_reward_model = create_reward_model(cfg.rnd_reward_model, policy.collect_mode.get_attribute('device'), tb_logger)
    episodic_reward_model = create_reward_model(
        cfg.episodic_reward_model, policy.collect_mode.get_attribute('device'), tb_logger
    )
    # ==========
    # Main loop
    # ==========
    # Learner's before_run hook.
    learner.call_hook('before_run')

    # Accumulate plenty of data at the beginning of training.
    if cfg.policy.get('random_collect_size', 0) > 0:
        # backup
        # action_space = collector_env.env_info().act_space
        # random_policy = PolicyFactory.get_random_policy(policy.collect_mode, action_space=action_space)
        # collector.reset_policy(random_policy)
        # collect_kwargs = commander.step()
        # # collect_kwargs.update({'action_shape':cfg.policy.model.action_shape}) # todo
        # new_data = collector.collect(n_sample=cfg.policy.random_collect_size, policy_kwargs=collect_kwargs)
        # replay_buffer.push(new_data, cur_collector_envstep=0)
        # collector.reset_policy(policy.collect_mode)
        random_collect(cfg.policy, policy, collector, collector_env, commander, replay_buffer)

    estimate_cnt = 0
    for iter in range(max_iterations):
        collect_kwargs = commander.step()  # {'eps': 0.95}
        # collect_kwargs.update({'action_shape':cfg.policy.model.action_shape}) # todo
        # Evaluate policy performance
        if evaluator.should_eval(learner.train_iter):
            stop, reward = evaluator.eval(learner.save_checkpoint, learner.train_iter, collector.envstep)
            if stop:
                break
        # new_data_count, target_new_data_count = 0, cfg.rnd_reward_model.get('target_new_data_count', 1)
        # while new_data_count < target_new_data_count:
        # Collect data by default config n_sample/n_episode
        if hasattr(cfg.policy.collect, "each_iter_n_sample"):  # TODO(pu)
            new_data = collector.collect(
                n_sample=cfg.policy.collect.each_iter_n_sample,
                train_iter=learner.train_iter,
                policy_kwargs=collect_kwargs
            )
        else:
            new_data = collector.collect(train_iter=learner.train_iter, policy_kwargs=collect_kwargs)
        # new_data_count += len(new_data)
        # collect data for reward_model training
        rnd_reward_model.collect_data(new_data)  # TODO(pu):
        episodic_reward_model.collect_data(new_data)  # TODO(pu):
        replay_buffer.push(new_data, cur_collector_envstep=collector.envstep)
        # update reward_model
        rnd_reward_model.train()
        # if iter % 10 == 0:  # TODO(pu):
        if (iter + 1) % cfg.rnd_reward_model.clear_buffer_per_iters == 0:
            rnd_reward_model.clear_data()
        episodic_reward_model.train()
        if (iter + 1) % cfg.episodic_reward_model.clear_buffer_per_iters == 0:
            episodic_reward_model.clear_data()  # TODO(pu):

        # Learn policy from collected data
        for i in range(cfg.policy.learn.update_per_collect):
            # Learner will train ``update_per_collect`` times in one iteration.
            train_data = replay_buffer.sample(learner.policy.get_attribute('batch_size'), learner.train_iter)
            if train_data is None:
                # It is possible that replay buffer's data count is too few to train ``update_per_collect`` times
                logging.warning(
                    "Replay buffer's data can only train for {} steps. ".format(i) +
                    "You can modify data collect config, e.g. increasing n_sample, n_episode."
                )
                break
            # TODO(pu) very important, otherwise the reward od the date in replay buffer will be modifyed
            train_data_modified = copy.deepcopy(train_data)
            # update train_data reward
            rnd_reward = rnd_reward_model.estimate(train_data_modified)  # TODO
            episodic_reward = episodic_reward_model.estimate(train_data_modified)  # TODO(pu)
            train_data_modified, estimate_cnt = fusion_reward(
                train_data_modified,
                rnd_reward,
                episodic_reward,
                nstep=cfg.policy.nstep,
                collector_env_num=cfg.policy.collect.env_num,
                tb_logger=tb_logger,
                estimate_cnt=estimate_cnt
            )
            learner.train(train_data_modified, collector.envstep)
            if learner.policy.get_attribute('priority'):
                replay_buffer.update(learner.priority_info)
        if cfg.policy.on_policy:
            # On-policy algorithm must clear the replay buffer.
            replay_buffer.clear()

    # Learner's after_run hook.
    learner.call_hook('after_run')
    return policy
