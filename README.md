# TSELM: Target Speaker Extraction using Discrete Tokens and Language Models
<!---->
<!-- [![Paper](https://img.shields.io/badge/Paper-red?&logo=arxiv)](https://arxiv.org/abs/2409.07841) -->
<!-- [![Demo](https://img.shields.io/badge/Demo-green?&logo=youtube)](https://tselmdemo.github.io/TSELM.demo/) -->

Official Implementation of TSELM: Target Speaker Extraction using Discrete Tokens and Language Models. 

To refer to the model class, check [exp/tselm/model.py](./exp/tselm/model.py) directly. Note 
that the mixed audio is clipped to length 48080 (3.05s x 16khz) and reference speech is clipped to 64080 (4.05s x 16khz) for training, respectively. 

## Abstract
We propose TSELM, a novel target speaker extraction network that leverages discrete tokens and language models.
TSELM utilizes multiple discretized layers from WavLM as input
tokens and incorporates cross-attention mechanisms to integrate
target speaker information. Language models are employed to
capture the sequence dependencies, while a scalable HiFi-GAN
is used to reconstruct the audio from the tokens. By applying a
cross-entropy loss, TSELM models the probability distribution of
output tokens, thus converting the complex regression problem of
audio generation into a classification task. Experimental results
show that TSELM achieves excellent results in speech quality
and comparable results in speech intelligibility.


## Pre-requisites

1. Install [SpeechBrain](https://github.com/speechbrain/speechbrain/tree/main) (We use the Conformer model from it). 
2. Install all dependencies from `requirements.txt`
3. Download the encoder(WavLM Large and Kmeans) and decoder(Scalable HiFiGAN) checkpoint. Details can be found in [Model](#pretrained-model) session.
4. Download the data and run the scripts following [data/README.md](./data/README.md).

### Pretrained Model
Befor running experiments, we need to download the following frozen pretrained models.

| Name         | Link                                                        | Result                       |
|--------------|-------------------------------------------------------------|----------------------------|
| WavLM Large  | https://huggingface.co/microsoft/wavlm-large/tree/main      | wavlm-large |
| Kmeans       | [Download Kmeans Checkpoint](https://huggingface.co/Beilong/TSELM/resolve/main/kmeans_ckpt/kmeans_wavlm_ckpt.tar.gz?download=true)  | kmeans_ckpt      |
| Scalable HiFiGAN | [Download HiFiGAN Checkpoint](https://huggingface.co/Beilong/TSELM/resolve/main/backend_ckpt/hifigan-wavlm-l1-3-7-18-23-k1000-LibriTTS.tar.gz?download=true) | hifigan-wavlm-l1-3-7-18-23-k1000-LibriTTS |

Note that for the output of WavLM Large, it is recommended to clone the whole repository or download the whole directory. For Kmeans and Scalable HiFiGAN, we need to extract them after downloading. 


## Training

The training config is specified using `hyperpyyaml` package, which is basically a reflection. 

The config for training `TSELM-L` can be found in [config/tselm_l.yaml](./config/tselm_l.yaml). Before training, you need to specify the config for the frozen pretrained models and other training details. Details can be found in [config/tselm_l.yaml](./config/tselm_l.yaml) and [config/README.md](./config/README.md). 

After configuration, you can run 
```shell
## Train the model using the config 
python train.py --config_path ./config/tselm_l.yaml --log ./log --ckpt_path ./ckpt/tselm_l 
```
- `--config_path` specifies the path to the config file.
- `--log` specifies the log output directory. All logs will be put here.
- `--ckpt_path` specifies the checkpoint directory. Training can be resumed using the same checkpoint path. 

After training, the best model will be at `<ckpt_path>/best.pth`. 


## Inference
To infer our model on libri2mix testset, for example, you can run

```shell
## Generate output audio on libri2mix testset
python inference.py -scp <path_to_libri2mix_test_scp_folder> \
  -config ./config/tselm_l.yaml \
  -ckpt <path_to_ckpt> \
  --output <path_to_output_folder> \
  -gpus cuda:0 cuda:1 cuda:2 cuda:3 \
  -proc 8
```

- `-scp` specifies the the path to the libri2mix testset folder containing `aux_s1.scp`, `s1.scp`, and `mix_clean.scp`. 
- `-config` specifies the config. This config needs to have the `model` field. 
- `-ckpt` specifies the model checkpoint.
- `--output` specifies the output directory. 
The output audio will be output to this folder. Their names will be the same as those in .scp files. 
- `-gpus` specifies the available gpus to run inference.
- `-proc` specifies the total number of processes to run the inference in parallel. It will 
use the provided gpus and divide the processes equally on each device. Data will be split equally to each process.


## Model Checkpoint

Our TSELM-L checkpoint can be downloaded [here](https://huggingface.co/Beilong/TSELM/resolve/main/model_ckpt/tselm_l.pth?download=true).

You can infer on the libri2mix testset by substituting the `-ckpt` with path to the checkpoint. 

Note that you still need to download the [pretrained models](#pretrained-model) and add the corresponding checkpoint folder to [config/tselm_l.yaml](./config/tselm_l.yaml).

