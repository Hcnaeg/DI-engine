from typing import Any, List, Union, Optional
import time
import gym
import numpy as np
from ding.envs import BaseEnv, BaseEnvTimestep, BaseEnvInfo
from ding.envs.common.env_element import EnvElement, EnvElementInfo
from ding.torch_utils import to_ndarray, to_list
from ding.utils import ENV_REGISTRY
from ding.envs.common import affine_transform


@ENV_REGISTRY.register('lunarlander')
class LunarLanderEnv(BaseEnv):

    def __init__(self, cfg: dict) -> None:
        self._cfg = cfg
        self._init_flag = False
        # env_id: LunarLander-v2, LunarLanderContinuous-v2
        self._env_id = cfg.env_id
        if 'Continuous' in self._env_id:
            self._act_scale = cfg.act_scale  # act_scale only works in continous env
        else:
            self._act_scale = False

    def reset(self) -> np.ndarray:
        if not self._init_flag:
            self._env = gym.make(self._cfg.env_id)
            self._init_flag = True
        if hasattr(self, '_seed') and hasattr(self, '_dynamic_seed') and self._dynamic_seed:
            np_seed = 100 * np.random.randint(1, 1000)
            self._env.seed(self._seed + np_seed)
        elif hasattr(self, '_seed'):
            self._env.seed(self._seed)
        self._final_eval_reward = 0
        obs = self._env.reset()
        obs = to_ndarray(obs).astype(np.float32)
        return obs

    def close(self) -> None:
        if self._init_flag:
            self._env.close()
        self._init_flag = False

    def render(self) -> None:
        self._env.render()

    def seed(self, seed: int, dynamic_seed: bool = True) -> None:
        self._seed = seed
        self._dynamic_seed = dynamic_seed
        np.random.seed(self._seed)

    def step(self, action: np.ndarray) -> BaseEnvTimestep:
        assert isinstance(action, np.ndarray), type(action)
        if action.shape == (1, ):
            action = action.squeeze()  # 0-dim array
        if self._act_scale:
            action = affine_transform(action, min_val=-1, max_val=1)
        obs, rew, done, info = self._env.step(action)
        # self._env.render()
        rew = float(rew)
        self._final_eval_reward += rew
        if done:
            info['final_eval_reward'] = self._final_eval_reward
        obs = to_ndarray(obs).astype(np.float32)
        rew = to_ndarray([rew])  # wrapped to be transfered to a array with shape (1,)
        return BaseEnvTimestep(obs, rew, done, info)

    def info(self) -> BaseEnvInfo:
        T = EnvElementInfo
        if self._cfg.env_id == 'LunarLanderContinuous-v2':
            return BaseEnvInfo(
                agent_num=1,
                obs_space=T(
                    (8, ),
                    {
                        'min': [float("-inf")] * 8,
                        'max': [float("inf")] * 8,
                        'dtype': np.float32,
                    },
                ),
                # [min, max) TODO(pu)
                act_space=T(
                    (2, ),
                    {
                        'min': float("-inf"),
                        'max': float("inf"),
                        'dtype': np.float32,
                    },
                ),
                rew_space=T(
                    (1, ),
                    {
                        'min': -1000.0,
                        'max': 1000.0,
                        'dtype': np.float32,
                    },
                ),
                use_wrappers=None,
            )
        else:
            return BaseEnvInfo(
                agent_num=1,
                obs_space=T(
                    (8, ),
                    {
                        'min': [float("-inf")] * 8,
                        'max': [float("inf")] * 8,
                        'dtype': np.float32,
                    },
                ),
                # [min, max)
                act_space=T(
                    (1, ),
                    {
                        'min': 0,
                        'max': 4,
                        'dtype': int,
                    },
                ),
                rew_space=T(
                    (1, ),
                    {
                        'min': -1000.0,
                        'max': 1000.0,
                        'dtype': np.float32,
                    },
                ),
                use_wrappers=None,
            )

    def __repr__(self) -> str:
        return "DI-engine LunarLander Env"

    def enable_save_replay(self, replay_path: Optional[str] = None) -> None:
        if replay_path is None:
            replay_path = './video'
        self._replay_path = replay_path
        # this function can lead to the meaningless result
        self._env = gym.wrappers.Monitor(
            self._env, self._replay_path, video_callable=lambda episode_id: True, force=True
        )
