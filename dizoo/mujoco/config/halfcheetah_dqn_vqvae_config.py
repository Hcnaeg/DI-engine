from easydict import EasyDict
from ding.entry import serial_pipeline_dqn_vqvae

nstep = 3
halfcheetah_dqn_default_config = dict(
    exp_name='debug_halfcheetah_dqn_vqvae_ved128_k128_ehsl256256128_upcr20_bs512_ed1e5_rbs1e6_seed0_3M',

    env=dict(
        env_id='HalfCheetah-v3',
        norm_obs=dict(use_norm=False, ),
        norm_reward=dict(use_norm=False, ),
        # (bool) Scale output action into legal range.
        use_act_scale=True,
        # Env number respectively for collector and evaluator.
        collector_env_num=8,
        evaluator_env_num=5,
        n_evaluator_episode=5,
        stop_value=12000,
        # stop_value=int(1e6),
    ),
    policy=dict(
        # Whether to use cuda for network.
        cuda=True,
        priority=False,
        random_collect_size=int(1e4),
        original_action_shape=6,
        vqvae_embedding_dim=128,  # ved
        model=dict(
            obs_shape=17,
            action_shape=int(128),  # num oof num_embeddings
            encoder_hidden_size_list=[256, 256, 128],
            # Whether to use dueling head.
            dueling=True,
        ),
        # Reward's future discount factor, aka. gamma.
        discount_factor=0.99,
        # How many steps in td error.
        nstep=nstep,
        # learn_mode config
        learn=dict(
            ignore_done=True,
            warm_up_update=int(1e4),
            rl_vae_update_circle=1,  # train rl 1 iter, vae 1 iter
            update_per_collect_rl=20, 
            update_per_collect_vae=10,

            batch_size=512,  # large batch size
            learning_rate=3e-4,
            learning_rate_vae=1e-4,
            # Frequency of target network update.
            target_update_freq=500,
        ),
        # collect_mode config
        collect=dict(
            # You can use either "n_sample" or "n_episode" in collector.collect.
            # Get "n_sample" samples per collect.
            n_sample=256,
            # Cut trajectories into pieces with length "unroll_len".
            unroll_len=1,
        ),
        # command_mode config
        other=dict(
            # Epsilon greedy with decay.
            eps=dict(
                # Decay type. Support ['exp', 'linear'].
                type='exp',
                start=1,
                end=0.05,
                decay=int(1e5),
            ),
            replay_buffer=dict(replay_buffer_size=int(1e6), )
        ),
    ),
)
halfcheetah_dqn_default_config = EasyDict(halfcheetah_dqn_default_config)
main_config = halfcheetah_dqn_default_config

halfcheetah_dqn_create_config = dict(
    env=dict(
        type='mujoco',
        import_names=['dizoo.mujoco.envs.mujoco_env'],
    ),
    env_manager=dict(type='base'),
    policy=dict(type='dqn_vqvae'),
)
halfcheetah_dqn_create_config = EasyDict(halfcheetah_dqn_create_config)
create_config = halfcheetah_dqn_create_config

if __name__ == "__main__":
    serial_pipeline_dqn_vqvae([main_config, create_config], seed=0)