from typing import List, Callable, Union, Any, TypeVar, Tuple, Dict, Optional
import collections
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Normal, Independent
from ding.torch_utils import one_hot, to_tensor
from ding.model.common import RegressionHead, ReparameterizationHead, DiscreteHead, MultiHead, \
    FCEncoder, ConvEncoder

class ExponentialMovingAverage(nn.Module):

    def __init__(self, decay: float, shape: Tuple[int]) -> None:
        super(ExponentialMovingAverage, self).__init__()
        self.decay = decay
        self.shape = shape
        self.reset()

    #@torch.no_grad
    def update(self, value: torch.Tensor) -> None:
        # i.e. self.hidden = (1.0 - self.decay) * value + self.decay * self.hidden
        self.count.add_(1)
        self.hidden -= (1.0 - self.decay) * (self.hidden - value)
        # ema correction
        # NOTE
        self.average = self.hidden / (1 - torch.pow(self.decay, self.count))

    @property
    def value(self) -> torch.Tensor:
        return self.average

    def reset(self, shape: Optional[Tuple] = None) -> None:
        if shape is None:
            shape = self.shape
        self.register_buffer('count', torch.zeros(1))
        self.register_buffer('hidden', torch.zeros(*shape))
        self.register_buffer('average', torch.zeros(*shape))


class VectorQuantizer(nn.Module):
    """
    Reference:
    [1] https://github.com/deepmind/sonnet/blob/v2/sonnet/src/nets/vqvae.py
    """

    def __init__(
        self,
        embedding_num: int,
        embedding_size: int = 128,
        beta: float = 0.25,
        is_ema: bool = False,
        is_ema_target: bool = False,
        eps_greedy_nearest: bool = False,
        embedding_table_onehot: bool =False,
    ):
        super(VectorQuantizer, self).__init__()
        self.K = embedding_num
        self.D = embedding_size
        self.beta = beta
        self.is_ema = is_ema
        self.is_ema_target = is_ema_target
        self.eps_greedy_nearest = eps_greedy_nearest
        self.embedding_table_onehot = embedding_table_onehot

        self.embedding = nn.Embedding(self.K, self.D)
        if self.embedding_table_onehot:
            self.embedding.weight.data = one_hot(torch.arange(self.D), self.D)  # B, K
        else:
            self.embedding.weight.data.uniform_(-1 / self.K, 1 / self.K)


        if self.is_ema:
            self.ema_N = ExponentialMovingAverage(0.99, (self.K, ))
            self.ema_m = ExponentialMovingAverage(0.99, (self.K, self.D))

    def train(self, encoding: torch.Tensor, eps=0.05) -> torch.Tensor:
        """
        Overview:
            input the encoding of actions, caculate the vqvae loss
        Arguments:
            - encoding shape: (B,D)
        """
        device = encoding.device
        encoding_shape = encoding.shape
        if len(encoding_shape)==3:
            # for multi-agent case, e.g. gobigger, 
            # if encoding shape is (B,A,D), where B is batch_size, A is agent_num, D is encoding_dim
            encoding = encoding.view(-1, encoding_shape[-1]) 
        quantized_index = self.encode(encoding)
        # print('torch.unique(quantized_index):', torch.unique(quantized_index))
        if self.eps_greedy_nearest:
            for i in range(encoding.shape[0]):
                if np.random.random() < eps:
                    quantized_index[i] = torch.randint(0, self.K, [1])
        quantized_one_hot = one_hot(quantized_index, self.K)  # B, K
        quantized_embedding = torch.matmul(quantized_one_hot, self.embedding.weight)

        # Compute the VQ Losses
        commitment_loss = F.mse_loss(encoding, quantized_embedding.detach())

        #  VQ-VAE dictionary updates with Exponential Moving Averages
        if self.is_ema:
            # (K, )
            self.ema_N.update(quantized_one_hot.sum(dim=0))
            # (B,K)->(K,B)  * (B,D)
            delta_m = torch.matmul(quantized_one_hot.permute(1, 0), encoding)  # K, D
            self.ema_m.update(delta_m)

            N = self.ema_N.value
            total = N.sum()
            normed_N = (N + 1e-5) / (total + self.K * 1e-5) * total
            target_embedding_value = self.ema_m.value / normed_N.unsqueeze(1)

            if self.is_ema_target:
                embedding_loss = F.mse_loss(self.embedding.weight, target_embedding_value)
            else:
                embedding_loss = torch.zeros(1, device=device)
                self.embedding.weight.data = target_embedding_value
        else:
            if not self.embedding_table_onehot:
                embedding_loss = F.mse_loss(quantized_embedding, encoding.detach())
            else:
                embedding_loss = torch.tensor(0.)

        vq_loss = commitment_loss * self.beta + embedding_loss
        # straight-through estimator for passing gradient from decoder, add the residue back to the encoding
        quantized_embedding = encoding + (quantized_embedding - encoding).detach()

        return quantized_index, quantized_embedding, vq_loss, embedding_loss, commitment_loss

    def encode(self, encoding: torch.Tensor) -> torch.Tensor:
        # # Method 2: Compute L2 distance between encoding and embedding weights
        # dist = torch.sum(flat_encoding ** 2, dim=1, keepdim=True) + \
        #        torch.sum(self.embedding.weight ** 2, dim=1) - \
        #        2 * torch.matmul(flat_encoding, self.embedding.weight.t())
        # # Get the encoding that has the min distance
        # quantized_index = torch.argmin(dist, dim=1).unsqueeze(1)

        # .sort()[1] take the index after sorted, [:,0] take the nearest index
        # return torch.cdist(encoding, self.embedding.weight, p=2).sort()[1][:, 0]
        """
        Overview:
            input the encoding of actions, find the nearest encoding index in embedding table
        Arguments:
            - encoding shape: (B,D) self.embedding.weight shape:(K,D)
            - return shape: (B), the nearest encoding index in embedding table
        """

        return torch.cdist(encoding, self.embedding.weight, p=2).min(dim=-1)[1]

    def decode(self, quantized_index: torch.Tensor) -> torch.Tensor:
        # Convert to one-hot encodings
        quantized_one_hot = one_hot(quantized_index, self.K)
        # Quantize the encoding
        quantized_embedding = torch.matmul(quantized_one_hot, self.embedding.weight)
        return quantized_embedding


class ActionVQVAE(nn.Module):

    def __init__(
            self,
            action_shape: Union[int, Dict],
            embedding_num: int,
            embedding_size: int = 128,
            hidden_dims: List = [256],
            beta: float = 0.25,
            vq_loss_weight: float = 1,
            is_ema: bool = False,
            is_ema_target: bool = False,
            eps_greedy_nearest: bool = False,
            cont_reconst_l1_loss: bool = False,
            cont_reconst_smooth_l1_loss: bool = False,
            categorical_head_for_cont_action: bool = False,
            n_atom: int = 51,
            gaussian_head_for_cont_action: bool = False,
            embedding_table_onehot: bool = False,
            vqvae_return_weight: bool =False,
    ) -> None:
        super(ActionVQVAE, self).__init__()

        self.action_shape = action_shape
        self.hidden_dims = hidden_dims
        self.vq_loss_weight = vq_loss_weight
        self.embedding_size = embedding_size
        self.embedding_num = embedding_num
        self.act = nn.ReLU()
        self.cont_reconst_l1_loss = cont_reconst_l1_loss
        self.cont_reconst_smooth_l1_loss = cont_reconst_smooth_l1_loss
        self.categorical_head_for_cont_action=categorical_head_for_cont_action
        self.n_atom = n_atom
        self.gaussian_head_for_cont_action=gaussian_head_for_cont_action
        self.embedding_table_onehot = embedding_table_onehot
        self.vqvae_return_weight = vqvae_return_weight

        # Encoder
        if isinstance(self.action_shape, int):  # continuous action
            action_encoder = nn.Sequential(nn.Linear(self.action_shape, self.hidden_dims[0]), self.act)
        elif isinstance(self.action_shape, dict):  # hybrid action
            # input action: concat(continuous action, one-hot encoding of discrete action)
            action_encoder = nn.Sequential(
                nn.Linear(
                    self.action_shape['action_type_shape'] + self.action_shape['action_args_shape'], self.hidden_dims[0]
                ), self.act
            )
        self.encoder = [
            action_encoder,
            nn.Linear(self.hidden_dims[0], self.hidden_dims[0]), self.act,
            nn.Linear(self.hidden_dims[0], self.embedding_size)
        ]
        self.encoder = nn.Sequential(*self.encoder)

        # VQ layer
        self.vq_layer = VectorQuantizer(embedding_num, embedding_size, beta, is_ema, is_ema_target, eps_greedy_nearest, embedding_table_onehot)

        # Decoder
        self.decoder = nn.Sequential(
            *[
                nn.Linear(self.embedding_size, self.hidden_dims[0]),
                self.act,
                nn.Linear(self.hidden_dims[0], self.hidden_dims[0]),
                self.act,
            ]
        )

        if isinstance(self.action_shape, int):  # continuous action
            if self.categorical_head_for_cont_action:
                # self.recons_action_head = nn.Sequential(nn.Linear(self.hidden_dims[0], self.action_shape*self.n_atom), nn.Tanh())
                self.recons_action_head = nn.Sequential(nn.Linear(self.hidden_dims[0], self.action_shape*self.n_atom))
            elif self.gaussian_head_for_cont_action:
                self.recons_action_head = ReparameterizationHead(
                    self.hidden_dims[0],
                    self.action_shape,
                    1,
                    sigma_type='conditioned',
                    activation=nn.ReLU(),
                    norm_type=None
                )
            else:
                self.recons_action_head = nn.Sequential(nn.Linear(self.hidden_dims[0], self.action_shape), nn.Tanh())

        elif isinstance(self.action_shape, dict):  # hybrid action
            # input action: concat(continuous action, one-hot encoding of discrete action)

            if self.categorical_head_for_cont_action:
                # self.recons_action_cont_head = nn.Sequential(
                #     nn.Linear(self.hidden_dims[0], self.action_shape['action_args_shape']*self.n_atom), nn.Tanh()
                # )
                self.recons_action_cont_head = nn.Sequential(
                    nn.Linear(self.hidden_dims[0], self.action_shape['action_args_shape']*self.n_atom))
            elif self.gaussian_head_for_cont_action:
                self.recons_action_cont_head = ReparameterizationHead(
                    self.hidden_dims[0],
                    self.action_shape['action_args_shape'],
                    1,
                    sigma_type='conditioned',
                    activation=nn.ReLU(),
                    norm_type=None
                )
            else:
                self.recons_action_cont_head = nn.Sequential(
                    nn.Linear(self.hidden_dims[0], self.action_shape['action_args_shape']), nn.Tanh()
                )
            

            # self.recons_action_disc_head = nn.Sequential(
            #     nn.Linear(self.hidden_dims[0], self.action_shape['action_type_shape']), nn.ReLU()
            # )
            # TODO
            self.recons_action_disc_head = nn.Sequential(
                nn.Linear(self.hidden_dims[0], self.action_shape['action_type_shape'])
            )

    def _get_action_embedding(self, data: Dict) -> torch.Tensor:
        if isinstance(self.action_shape, int):  # continuous action
            action_embedding = data['action']
        elif isinstance(self.action_shape, dict):  # hybrid action
            action_disc_onehot = one_hot(data['action']['action_type'], num=self.action_shape['action_type_shape'])
            action_embedding = torch.cat([action_disc_onehot, data['action']['action_args']], dim=-1)
        return action_embedding

    def _recons_action(
        self,
        action_decoding: torch.Tensor,
        target_action: Union[torch.Tensor, Dict[str, torch.Tensor]] = None,
        weight: Union[torch.Tensor, Dict[str, torch.Tensor]] = None
    ) -> Tuple[Union[torch.Tensor, Dict[str, torch.Tensor]], torch.Tensor]:
        sigma=None # debug
        if isinstance(self.action_shape, int):  # continuous action
            if self.categorical_head_for_cont_action:
                support = torch.linspace(-1, 1, self.n_atom).to(action_decoding.device)  # TODO
                recons_action_logits = self.recons_action_head(action_decoding).view(-1, self.action_shape, self.n_atom)
                recons_action_probs = F.softmax(recons_action_logits, dim=-1)  # TODO
                recons_action = torch.sum(recons_action_probs * support, dim=-1)
                # recons_action_logits: tanh 
                # recons_action = torch.mean(recons_action_logits * support, dim=-1)
            elif self.gaussian_head_for_cont_action:
                mu_sigma_dict = self.recons_action_head(action_decoding)
                (mu, sigma) = (mu_sigma_dict['mu'], mu_sigma_dict['sigma'])
                # print(mu, sigma)
                dist = Independent(Normal(mu, sigma), 1)
                recons_action_sample = dist.rsample()
                recons_action = torch.tanh(recons_action_sample)
            else:
                recons_action = self.recons_action_head(action_decoding)

        elif isinstance(self.action_shape, dict):  # hybrid action
            if self.categorical_head_for_cont_action:
                support = torch.linspace(-1, 1, self.n_atom).to(action_decoding.device)  # TODO
                recons_action_logits = self.recons_action_cont_head(action_decoding).view(-1, self.action_shape['action_args_shape'], self.n_atom)
                recons_action_probs = F.softmax(recons_action_logits, dim=-1)  # TODO
                recons_action_cont = torch.sum(recons_action_probs * support, dim=-1)
                # recons_action_logits: tanh 
                # recons_action_connt = torch.mean(recons_action_logits * support, dim=-1)
            elif self.gaussian_head_for_cont_action:
                mu_sigma_dict = self.recons_action_head(action_decoding)
                (mu, sigma) = (mu_sigma_dict['mu'], mu_sigma_dict['sigma'])
                dist = Independent(Normal(mu, sigma), 1)
                recons_action_sample = dist.rsample()
                recons_action_cont = torch.tanh(recons_action_sample)
            else:
                recons_action_cont = self.recons_action_cont_head(action_decoding)

            recons_action_disc_logit = self.recons_action_disc_head(action_decoding)
            recons_action_disc = torch.argmax(recons_action_disc_logit, dim=-1)
            recons_action = {
                'action_args': recons_action_cont,
                'action_type': recons_action_disc,
                'logit': recons_action_disc_logit
            }

        if target_action is None:
            return recons_action, sigma
        else:
            if isinstance(self.action_shape, int):  # continuous action
                if  self.cont_reconst_l1_loss:
                    recons_loss = F.l1_loss(recons_action, target_action)
                    recons_loss_none_reduction = F.l1_loss(recons_action, target_action, reduction='none').mean(-1)
                elif self.cont_reconst_smooth_l1_loss:
                    recons_loss = F.smooth_l1_loss(recons_action, target_action)
                    recons_loss_none_reduction = F.smooth_l1_loss(recons_action, target_action, reduction='none').mean(-1)
                else:
                    if self.vqvae_return_weight and weight is not None:
                        recons_loss = (weight.reshape(-1,1) * F.mse_loss(recons_action, target_action, reduction='none')).mean()
                    else:
                        recons_loss = F.mse_loss(recons_action, target_action)
                    recons_loss_none_reduction = F.mse_loss(recons_action, target_action, reduction='none').mean(-1)

            elif isinstance(self.action_shape, dict):  # hybrid action
                if  self.cont_reconst_l1_loss:
                    recons_loss_cont = F.l1_loss(recons_action['action_args'], target_action['action_args'].view(-1,target_action['action_args'].shape[-1]))
                    recons_loss_cont_none_reduction = F.l1_loss(recons_action['action_args'], target_action['action_args'].view(-1,target_action['action_args'].shape[-1]), reduction='none').mean(-1)
                elif  self.cont_reconst_smooth_l1_loss:
                    recons_loss_cont = F.smooth_l1_loss(recons_action['action_args'], target_action['action_args'].view(-1,target_action['action_args'].shape[-1]))
                    recons_loss_cont_none_reduction = F.smooth_l1_loss(recons_action['action_args'], target_action['action_args'].view(-1,target_action['action_args'].shape[-1]), reduction='none').mean(-1)
                else:
                    recons_loss_cont = F.mse_loss(recons_action['action_args'], target_action['action_args'].view(-1,target_action['action_args'].shape[-1]))
                    recons_loss_cont_none_reduction = F.mse_loss(recons_action['action_args'], target_action['action_args'].view(-1,target_action['action_args'].shape[-1]), reduction='none').mean(-1)

                recons_loss_disc = F.cross_entropy(recons_action['logit'], target_action['action_type'].view(-1))
                recons_loss_disc_none_reduction = F.cross_entropy(recons_action['logit'], target_action['action_type'].view(-1), reduction='none').mean(-1)

                # here view(-1) is to be compatiable with multi_agent case, e.g. gobigger
                recons_loss = recons_loss_cont + recons_loss_disc
                recons_loss_none_reduction = recons_loss_cont_none_reduction + recons_loss_disc_none_reduction


            return recons_action, recons_loss, recons_loss_none_reduction, sigma

    def train(self, data: Dict, warmup: bool=False) -> Dict[str, torch.Tensor]:
        action_embedding = self._get_action_embedding(data)
        encoding = self.encoder(action_embedding)
        quantized_index, quantized_embedding, vq_loss, embedding_loss, commitment_loss = self.vq_layer.train(encoding)
        action_decoding = self.decoder(quantized_embedding)
        if self.vqvae_return_weight and not warmup:
            recons_action, recons_loss, recons_loss_none_reduction, sigma = self._recons_action(action_decoding, data['action'], data['return_normalization'])
        else:
            recons_action, recons_loss, recons_loss_none_reduction, sigma = self._recons_action(action_decoding, data['action'])
        
        total_vqvae_loss = recons_loss + self.vq_loss_weight * vq_loss
        return {
            'quantized_index': quantized_index,
            'recons_loss_none_reduction': recons_loss_none_reduction, # use for rl priority in dqn_vqvae
            'sigma': sigma,
            'total_vqvae_loss': total_vqvae_loss,
            'recons_loss': recons_loss,
            'vq_loss': vq_loss,
            'embedding_loss': embedding_loss,
            'commitment_loss': commitment_loss
        }

    def encode(self, data: Dict) -> torch.Tensor:
        with torch.no_grad():
            action_embedding = self._get_action_embedding(data)
            encoding = self.encoder(action_embedding)
            quantized_index = self.vq_layer.encode(encoding)
            return quantized_index

    def decode(self, quantized_index: torch.Tensor) -> Dict:
        with torch.no_grad():
            quantized_embedding = self.vq_layer.decode(quantized_index)
            action_decoding = self.decoder(quantized_embedding)
            recons_action, sigma = self._recons_action(action_decoding)
            return {'recons_action': recons_action}