from typing import Any, Union, List, Optional
import copy
import numpy as np
from easydict import EasyDict
import gym

from ding.envs import BaseEnv, BaseEnvTimestep, BaseEnvInfo, update_shape
from ding.envs.common.env_element import EnvElement, EnvElementInfo
from ding.envs.common.common_function import affine_transform
from ding.torch_utils import to_ndarray, to_list
from ding.utils import ENV_REGISTRY
from .mujoco_wrappers import wrap_mujoco

MUJOCO_INFO_DICT = {
    'Ant-v3': BaseEnvInfo(
        agent_num=1,
        obs_space=EnvElementInfo(
            shape=(111, ),
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf"),
                'dtype': np.float32
            },
        ),
        act_space=EnvElementInfo(
            shape=(8, ),
            value={
                'min': -1.0,
                'max': 1.0,
                'dtype': np.float32
            },
        ),
        rew_space=EnvElementInfo(
            shape=1,
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf")
            },
        ),
        use_wrappers=None,
    ),
    'Hopper-v2': BaseEnvInfo(
        agent_num=1,
        obs_space=EnvElementInfo(
            shape=(11, ),
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf"),
                'dtype': np.float32
            },
        ),
        act_space=EnvElementInfo(
            shape=(3, ),
            value={
                'min': -1.0,
                'max': 1.0,
                'dtype': np.float32
            },
        ),
        rew_space=EnvElementInfo(
            shape=1,
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf")
            },
        ),
        use_wrappers=None,
    ),
    'Walker2d-v2': BaseEnvInfo(
        agent_num=1,
        obs_space=EnvElementInfo(
            shape=(17, ),
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf"),
                'dtype': np.float32
            },
        ),
        act_space=EnvElementInfo(
            shape=(6, ),
            value={
                'min': -1.0,
                'max': 1.0,
                'dtype': np.float32
            },
        ),
        rew_space=EnvElementInfo(
            shape=1,
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf")
            },
        ),
        use_wrappers=None,
    ),
    'HalfCheetah-v3': BaseEnvInfo(
        agent_num=1,
        obs_space=EnvElementInfo(
            shape=(17, ),
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf"),
                'dtype': np.float32
            },
        ),
        act_space=EnvElementInfo(
            shape=(6, ),
            value={
                'min': -1.0,
                'max': 1.0,
                'dtype': np.float32
            },
        ),
        rew_space=EnvElementInfo(
            shape=1,
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf")
            },
        ),
        use_wrappers=None,
    ),
    'Hopper-v3': BaseEnvInfo(
        agent_num=1,
        obs_space=EnvElementInfo(
            shape=(11, ),
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf"),
                'dtype': np.float32
            },
        ),
        act_space=EnvElementInfo(
            shape=(3, ),
            value={
                'min': -1.0,
                'max': 1.0,
                'dtype': np.float32
            },
        ),
        rew_space=EnvElementInfo(
            shape=1,
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf")
            },
        ),
        use_wrappers=None,
    ),
    'InvertedPendulum-v2': BaseEnvInfo(
        agent_num=1,
        obs_space=EnvElementInfo(
            shape=(4, ),
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf"),
                'dtype': np.float32
            },
        ),
        act_space=EnvElementInfo(
            shape=(1, ),
            value={
                'min': -1.0,
                'max': 1.0,
                'dtype': np.float32
            },
        ),
        rew_space=EnvElementInfo(
            shape=1,
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf")
            },
        ),
        use_wrappers=None,
    ),
    'InvertedDoublePendulum-v2': BaseEnvInfo(
        agent_num=1,
        obs_space=EnvElementInfo(
            shape=(11, ),
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf"),
                'dtype': np.float32
            },
        ),
        act_space=EnvElementInfo(
            shape=(1, ),
            value={
                'min': -1.0,
                'max': 1.0,
                'dtype': np.float32
            },
        ),
        rew_space=EnvElementInfo(
            shape=1,
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf")
            },
        ),
        use_wrappers=None,
    ),
    'Reacher-v2': BaseEnvInfo(
        agent_num=1,
        obs_space=EnvElementInfo(
            shape=(11, ),
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf"),
                'dtype': np.float32
            },
        ),
        act_space=EnvElementInfo(
            shape=(2, ),
            value={
                'min': -1.0,
                'max': 1.0,
                'dtype': np.float32
            },
        ),
        rew_space=EnvElementInfo(
            shape=1,
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf")
            },
        ),
        use_wrappers=None,
    ),
    'Walker2d-v3': BaseEnvInfo(
        agent_num=1,
        obs_space=EnvElementInfo(
            shape=(17, ),
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf"),
                'dtype': np.float32
            },
        ),
        act_space=EnvElementInfo(
            shape=(6, ),
            value={
                'min': -1.0,
                'max': 1.0,
                'dtype': np.float32
            },
        ),
        rew_space=EnvElementInfo(
            shape=1,
            value={
                'min': np.float64("-inf"),
                'max': np.float64("inf")
            },
        ),
        use_wrappers=None,
    ),
}


@ENV_REGISTRY.register('mujoco')
class MujocoEnv(BaseEnv):

    @classmethod
    def default_config(cls: type) -> EasyDict:
        cfg = EasyDict(copy.deepcopy(cls.config))
        cfg.cfg_type = cls.__name__ + 'Dict'
        return cfg

    config = dict(
        use_act_scale=False,
        delay_reward_step=0,
    )

    def __init__(self, cfg: dict) -> None:
        self._cfg = cfg
        self._use_act_scale = cfg.use_act_scale
        self._delay_reward_step = cfg.delay_reward_step
        self._init_flag = False
        self._replay_path = None

    def reset(self) -> np.ndarray:
        if not self._init_flag:
            self._env = self._make_env(only_info=False)
            self._init_flag = True
        if hasattr(self, '_seed') and hasattr(self, '_dynamic_seed') and self._dynamic_seed:
            np_seed = 100 * np.random.randint(1, 1000)
            self._env.seed(self._seed + np_seed)
        elif hasattr(self, '_seed'):
            self._env.seed(self._seed)
        if self._replay_path is not None:
            self._env = gym.wrappers.Monitor(
                self._env, self._replay_path, video_callable=lambda episode_id: True, force=True
            )
            self._env = gym.wrappers.RecordVideo(self._env, './videos/' + str('time()') + '/')  # time()
        obs = self._env.reset()
        obs = to_ndarray(obs).astype('float32')
        return obs

    def close(self) -> None:
        if self._init_flag:
            self._env.close()
        self._init_flag = False

    def seed(self, seed: int, dynamic_seed: bool = True) -> None:
        self._seed = seed
        self._dynamic_seed = dynamic_seed
        np.random.seed(self._seed)

    def step(self, action: Union[np.ndarray, list]) -> BaseEnvTimestep:
        action = to_ndarray(action)
        if self._use_act_scale:
            action_range = self.info().act_space.value
            action = affine_transform(action, min_val=action_range['min'], max_val=action_range['max'])
        obs, rew, done, info = self._env.step(action)
        obs = to_ndarray(obs).astype(np.float32)
        rew = to_ndarray([rew]).astype(np.float32)
        return BaseEnvTimestep(obs, rew, done, info)

    def info(self) -> BaseEnvInfo:
        if self._cfg.env_id in MUJOCO_INFO_DICT:
            info = copy.deepcopy(MUJOCO_INFO_DICT[self._cfg.env_id])
            info.use_wrappers = self._make_env(only_info=True)
            obs_shape, act_shape, rew_shape = update_shape(
                info.obs_space.shape, info.act_space.shape, info.rew_space.shape, info.use_wrappers.split('\n')
            )
            info.obs_space.shape = obs_shape
            info.act_space.shape = act_shape
            info.rew_space.shape = rew_shape
            return info
        else:
            keys = MUJOCO_INFO_DICT.keys()
            raise NotImplementedError('{} not found in MUJOCO_INFO_DICT [{}]'.format(self._cfg.env_id, keys))

    def _make_env(self, only_info=False):
        return wrap_mujoco(
            self._cfg.env_id,
            norm_obs=self._cfg.get('norm_obs', None),
            norm_reward=self._cfg.get('norm_reward', None),
            delay_reward_step=self._delay_reward_step,
            only_info=only_info
        )

    def enable_save_replay(self, replay_path: Optional[str] = None) -> None:
        if replay_path is None:
            replay_path = './video'
        self._replay_path = replay_path

    def __repr__(self) -> str:
        return "DI-engine Mujoco Env({})".format(self._cfg.env_id)

    @staticmethod
    def create_collector_env_cfg(cfg: dict) -> List[dict]:
        collector_cfg = copy.deepcopy(cfg)
        collector_env_num = collector_cfg.pop('collector_env_num', 1)
        return [collector_cfg for _ in range(collector_env_num)]

    @staticmethod
    def create_evaluator_env_cfg(cfg: dict) -> List[dict]:
        evaluator_cfg = copy.deepcopy(cfg)
        evaluator_env_num = evaluator_cfg.pop('evaluator_env_num', 1)
        evaluator_cfg.norm_reward.use_norm = False
        return [evaluator_cfg for _ in range(evaluator_env_num)]
