# The model class for TSELM model
from typing import List
import torch.nn as nn
import torch
import torch.nn.functional as F
import copy

from utils.wav import truc_wav, split_audio


class Model(nn.Module):
    def __init__(
        self,
        hifi_gan: nn.Module,  ##
        discrete_ssl: nn.Module,
        ssl_layers: List[int],
        attention_mlp: nn.Module,
        lm_model: nn.Module,
        embedding: nn.Module,
        head: nn.Module,
        fusion: nn.Module,
        film: nn.Module,
        fusion_norm: nn.Module,
        vocab_size: int,
        mix_continuous=False,
        concat_regi=True,
    ):
        """
        The model class for TSELM based models

        Arguments:
            mix_continuous: Whether to keep the mix continuous with tokenization
            concat_regi: Whether to concat reference audio to mixture

        """
        super().__init__()
        self.hifi_gan = hifi_gan
        self.discrete_ssl = discrete_ssl
        self.ssl_layers = ssl_layers
        self.attention_mlp = attention_mlp
        self.embedding = embedding
        self.vocab_size = vocab_size
        self.head = head
        self.lm = lm_model
        self.attention_mlp_regi = copy.deepcopy(attention_mlp)
        self.embedding_regi = copy.deepcopy(embedding)
        self.concat_regi = concat_regi
        self.mix_continuous = mix_continuous
        self.fusion = fusion
        self.film = film
        self.fusion_norm = fusion_norm

    @torch.no_grad()
    def sig_to_toks(self, audio):
        """
        Discretize audio to tokens
        
        Arguments
        ---------
        audio: torch.Tensor
            shape: [B, T]
        
        Return
        ------
        toks: torch.Tensor
            shape: [B, N, K] where N is the time dimension and K is the number of layers 
            
        """
        toks, _, _ = self.discrete_ssl(audio, SSL_layers=self.ssl_layers)
        return toks  # [B, N, K]

    @torch.no_grad()
    def toks_to_sig(self, toks):
        """
        Reconstruct audio from tokens

        Arguments
        ---------
        toks: torch.Tensor
            shape: [B, N, K]
        
        Return
        ------
        audio: torch.Tensor
            shape: [B, T]

        """
        # toks: [B, N, K]
        self.hifi_gan.device = toks.device
        self.hifi_gan.to(toks.device)
        all_layer_ids = [1, 3, 7, 12, 18, 23]
        offsets = torch.arange(
            0,
            len(all_layer_ids) * self.vocab_size,
            self.vocab_size,
            device=toks.device,
        )
        offset_idxes = [all_layer_ids.index(x) for x in self.ssl_layers]
        offsets = offsets[offset_idxes]
        toks = toks + offsets + 1

        # Handle missing codebooks
        if len(self.ssl_layers) < len(all_layer_ids):
            full_toks = torch.zeros(
                *toks.shape[:2],
                len(all_layer_ids),
                dtype=toks.dtype,
                device=toks.device,
            )
            for i, idx in enumerate(offset_idxes):
                full_toks[..., idx] = toks[..., i]
            toks = full_toks
        self.hifi_gan.tokenize = False
        sig = self.hifi_gan(toks)  # [B,T]
        return sig

    @torch.no_grad()
    def recon(self, toks: torch.Tensor):
        """
        Reconstruct the audio using the token and vocoder.

        Args:
            toks: the tokens of shape [B,N,K]
        Returns:
            audio: the audio of shape [B, T]
        """
        toks = toks.unsqueeze(2)  # [B, N, 1, K]
        toks = toks.movedim(-2, -3).contiguous()  # [B,S,N,K]
        rec_sig = self.toks_to_sig(toks.flatten(end_dim=1))  # [BS,T]
        return rec_sig

    def _error(self, out_toks, true_toks):
        """
        Calculate the error in percentage (0-100)
        """
        error = (1 - (out_toks == true_toks).sum() / out_toks.numel()) * 100
        return error

    def _emb(self, toks, embedding, attention_mlp):
        in_embs = embedding(toks)  # [B,N,K,H]
        att_w = attention_mlp(in_embs)  # [B,N,K,1]
        in_embs = torch.matmul(att_w.transpose(2, -1), in_embs).squeeze(-2)  # [B, N, H]
        return in_embs

    def _emb_ssl(self, audio, attention_mlp, start=200, length=150):
        """
        Get the embedding of the continuous ssl model

        Args:
            audio: [B, T]
            attention_mlp: attention_mlp layer
            start: the start of the embedding to apply attention
            length: the length of the embedding
        Return:
            emb: [B, N, K], where the N is the middle length after concatenation with register audio
        """
        with torch.no_grad():
            in_embs: torch.Tensor = self.discrete_ssl.ssl_model(audio)[
                self.ssl_layers
            ]  # [K,B,N,H]
        in_embs = in_embs.movedim(0, -2)  # [B,N,K,H]
        in_embs = in_embs[:, start : start + length]
        att_w = attention_mlp(in_embs)  # [B,N,K,1]
        in_embs = torch.matmul(att_w.transpose(2, -1), in_embs).squeeze(-2)  # [B, N, H]
        return in_embs

    def inference(self, mix, regi):
        """
        mix: [1,T] torch audio 2d
        regi: [1,T] torch audio 2d used as register audio
        """
        mix_array = split_audio(mix.squeeze(0), 48080)  # [T]
        regi = truc_wav(regi.squeeze(0), length=64080).unsqueeze(0)  # [1,T]
        aux_list = []
        for audio in mix_array:
            audio = audio.unsqueeze(0)  # [1,T]
            out_toks = self.forward(audio, None, regi, inference=True)  # [B,N,K]
            aux = self.recon(out_toks)  # [1, T]
            aux_list.append(aux)
        recon = torch.cat(aux_list, dim=1)  # [1, T']
        length = min(mix.size(1), recon.size(1))
        recon = recon[:, :length]
        return recon, int(length)

    def forward(self, mix, clean, regi, inference=False):
        """
        Args:
            mix: mix audio [B,T]
            clean1: clean 1 audio [B,T]
            regi: reference audio [B,T]
            inference: boolean standing for if inference 
        Returns:
            if inference is False, return (loss, out_toks [B,N,K], true_toks [B, N,K], and error)
            else: return the out_toks [B,N,K]
        """
        if self.concat_regi:
            mix_audio = torch.cat([regi, mix, regi], dim=1)  # [B, T]
            assert mix_audio.size(1) == 176240  ##
            if self.mix_continuous is False:
                mix_toks = self.sig_to_toks(mix_audio)  # [B,N,K]
                mix_toks = mix_toks[:, 200 : 200 + 150, :].contiguous()  # [B, N, K]
                mix_embs = self._emb(
                    mix_toks, self.embedding, self.attention_mlp
                )  # [B, N, H]
            else:
                mix_embs = self._emb_ssl(mix_audio, self.attention_mlp, 200, 150)
        else:
            mix_audio = mix
            assert mix_audio.size(1) == 48080
            if self.mix_continuous is False:
                mix_toks = self.sig_to_toks(mix_audio)  # [B,N,K]
                mix_toks = mix_toks.contiguous()  # [B, N, K]
                mix_embs = self._emb(
                    mix_toks, self.embedding, self.attention_mlp
                )  # [B, N, H]
            else:
                mix_embs = self._emb_ssl(mix_audio, self.attention_mlp, 0, 150)
        regi_toks = self.sig_to_toks(regi)  # [B, N, K]
        regi_emb = self._emb(regi_toks, self.embedding_regi, self.attention_mlp_regi)
        aux = self.fusion(mix_embs, regi_emb)[0]
        aux = self.film(mix_embs, aux)
        aux = self.fusion_norm(aux.transpose(1, 2)).transpose(1, 2)
        hyp_embs, _ = self.lm(aux, None)  # [B, N, H]
        probs: torch.Tensor = self.head(
            hyp_embs
        )  # [B,N,X(len(ssl_layers) * vocab_size)]
        probs = probs.reshape(
            len(hyp_embs), -1, len(self.ssl_layers), self.vocab_size
        )  # [B,N,K,C]
        out_toks = torch.argmax(probs, dim=3)  # [B, N, K]
        if not inference:
            ## training
            true_toks = self.sig_to_toks(clean)  # [B, N, K]
            loss = F.cross_entropy(probs.flatten(end_dim=-2), true_toks.flatten())
            return (loss, out_toks, true_toks, self._error(out_toks, true_toks))
        else:
            return out_toks
