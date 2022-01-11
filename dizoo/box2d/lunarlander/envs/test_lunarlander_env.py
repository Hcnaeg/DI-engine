from time import time
import pytest
import numpy as np
from easydict import EasyDict
from dizoo.box2d.lunarlander.envs import LunarLanderEnv


@pytest.mark.envtest
@pytest.mark.parametrize(
    'cfg', [
        EasyDict({
            'env_id': 'LunarLander-v2',
            'act_scale': False
        }),
        EasyDict({
            'env_id': 'LunarLanderContinuous-v2',
            'act_scale': True
        })
    ]
)
class TestLunarLanderEnvEnv:

    def test_naive(self, cfg):
        env = LunarLanderEnv(cfg)
        env.seed(314)
        assert env._seed == 314
        obs = env.reset()
        assert obs.shape == (8, )
        act_val = env.info().act_space.value
        min_val, max_val = act_val['min'], act_val['max']
        for i in range(10):
            if 'Continuous' in cfg.env_id:
                random_action = np.random.random(size=env.info().act_space.shape)
            else:
                random_action = np.random.randint(min_val, max_val, size=(1, ))
            timestep = env.step(random_action)
            print(timestep)
            assert isinstance(timestep.obs, np.ndarray)
            assert isinstance(timestep.done, bool)
            assert timestep.obs.shape == (8, )
            assert timestep.reward.shape == (1, )
            assert timestep.reward >= env.info().rew_space.value['min']
            assert timestep.reward <= env.info().rew_space.value['max']
            # assert isinstance(timestep, tuple)
        print(env.info())
        env.close()
