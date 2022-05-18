from easydict import EasyDict
import os
module_path = os.path.dirname(__file__)

nstep = 3
num_actuators=4
gym_hybrid_dqn_default_config = dict(
    env=dict(
        collector_env_num=8,
        evaluator_env_num=8,
        # (bool) Scale output action into legal range [-1, 1].
        act_scale=True,
        # env_id='Sliding-v0',
        # env_id='Moving-v0',
        env_id='HardMove-v0',
        num_actuators=num_actuators,  # only for 'HardMove-v0'
        n_evaluator_episode=8,
        # stop_value=2,
        stop_value=999,
    ),
    policy=dict(
        # TODO(pu)
        # learned_model_path=module_path + '/learned_model_path/ckpt_best.pth.tar',

        # Whether to use cuda for network.
        cuda=True,
        # Reward's future discount factor, aka. gamma.
        discount_factor=0.99,
        # How many steps in td error.
        nstep=nstep,
        # learn_mode config
        action_space='hybrid',
        eps_greedy_nearest=False, # TODO
        is_ema_target=False,  # use EMA

        is_ema=False,  # no use EMA # TODO
        # is_ema=True,  # use EMA
        # for 'Sliding-v0','Moving-v0'
        # original_action_shape=dict(
        #             action_type_shape=3,
        #             action_args_shape=2,
        #         ),
        # for 'HardMove-v0'
        original_action_shape=dict( 
                action_type_shape=int(2** num_actuators),  # 2**4=16, 2**6=64, 2**8=256, 2**10=1024
                action_args_shape=int(num_actuators), # 4,6,8,10
            ),
        random_collect_size=int(5e4),
        # random_collect_size=int(1),  # debug
        vqvae_embedding_dim=64,  # ved: D
        vqvae_hidden_dim=[256],  # vhd
        # vqvae_hidden_dim=[512],  # vhd
        # vqvae_hidden_dim=[1024],  # vhd
        vq_loss_weight=0.1,
        replay_buffer_size_vqvae=int(1e6),
        priority=False,
        priority_IS_weight=False,
        # TODO: weight RL loss according to the reconstruct loss, because in 
        # In the area with large reconstruction loss, the action reconstruction is inaccurate, that is, the (\hat{x}, r) does not match, 
        # and the corresponding Q value is inaccurate. The update should be reduced to avoid wrong gradient.
        rl_reconst_loss_weight=False,
        rl_reconst_loss_weight_min=0.2,
        # priority_vqvae=True,
        # priority_IS_weight_vqvae=True,
        # cont_reconst_l1_loss=True,
        priority_vqvae=False,
        priority_IS_weight_vqvae=False,
        priority_vqvae_min=0.2,
        cont_reconst_l1_loss=False,
        cont_reconst_smooth_l1_loss=False,
        vavae_pretrain_only=True,   # if  vavae_pretrain_only=True
        recompute_latent_action=False,
        # distribution_head_for_cont_action=True,
        distribution_head_for_cont_action=False,
        n_atom=51,
        model=dict(
            obs_shape=10,
            action_shape=int(64),  # num oof num_embeddings: K
            # encoder_hidden_size_list=[128, 128, 64],  # small net
            encoder_hidden_size_list=[256, 256, 128],  # middle net
            # encoder_hidden_size_list=[512, 512, 256],  # large net
            # Whether to use dueling head.
            dueling=True,
        ),
        learn=dict(
            reconst_loss_stop_value=1e-6, # TODO
            constrain_action=False,  # TODO
            warm_up_update=int(1e4),
            # warm_up_update=int(1), # debug

            rl_vae_update_circle=1,  # train rl 1 iter, vae 1 iter
            update_per_collect_rl=20,
            update_per_collect_vae=20,

            rl_batch_size=512,
            vqvae_batch_size=512,

            learning_rate=3e-4,
            learning_rate_vae=3e-4,
            # Frequency of target network update.
            # target_update_theta=0.001,
            target_update_freq=500,


            rl_clip_grad=True,
            vqvae_clip_grad=True,
            grad_clip_type='clip_norm',
            grad_clip_value=0.5,

            # add noise in original continuous action
            noise=False,
            # noise=True,
            noise_sigma=0.1,
            noise_range=dict(
            min=-0.5,
            max=0.5,
            ),
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
gym_hybrid_dqn_default_config = EasyDict(gym_hybrid_dqn_default_config)
main_config = gym_hybrid_dqn_default_config

gym_hybrid_dqn_create_config = dict(
    env=dict(
        type='gym_hybrid',
        import_names=['dizoo.gym_hybrid.envs.gym_hybrid_env'],
    ),
    env_manager=dict(type='subprocess'),
    # env_manager=dict(type='base'),
    policy=dict(type='dqn_vqvae'),
)
gym_hybrid_dqn_create_config = EasyDict(gym_hybrid_dqn_create_config)
create_config = gym_hybrid_dqn_create_config


def train(args):
    # main_config.exp_name = 'data_sliding/dqn_noema_smallnet_k16_upcr20' + '_seed' + f'{args.seed}'+'_3M'
    # main_config.exp_name = 'data_moving/dqn_noema_smallnet_k16_upcr20_vqloss0.1' + '_seed' + f'{args.seed}'+'_3M'
    # main_config.exp_name = 'data_hardmove_n4/dqn_noema_middlenet_k64_noise_history' + '_seed' + f'{args.seed}'+'_3M'
    # main_config.exp_name = 'data_hardmove_n10_25/dqn_noema_middlenet_k64_noise_history_vhd512' + '_seed' + f'{args.seed}'+'_3M'
    # main_config.exp_name = 'data_hardmove_n4_25/dqnvqvae_noema_middlenet_k64_pretrainonly_atom51_softmax' + '_seed' + f'{args.seed}'+'_3M'
    main_config.exp_name = 'data_hardmove_n4_25/dqnvqvae_noema_middlenet_k64_pretrainonly' + '_seed' + f'{args.seed}'+'_3M'


    serial_pipeline_dqn_vqvae([copy.deepcopy(main_config), copy.deepcopy(create_config)], seed=args.seed,max_env_step=int(3e6))


if __name__ == "__main__":
    import copy
    import argparse
    from ding.entry import serial_pipeline_dqn_vqvae

    for seed in [0,1,2]:
        parser = argparse.ArgumentParser()
        parser.add_argument('--seed', '-s', type=int, default=seed)
        args = parser.parse_args()

        train(args)
