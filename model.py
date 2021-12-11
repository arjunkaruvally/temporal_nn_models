import os
import torch
from torch import nn
from convolutional_lstm import ConvLSTM
from data import build_dataloader
from torch.nn import functional as F


def peak_signal_to_noise_ratio(true, pred):
    return 10.0 * torch.log(torch.tensor(1.0) / F.mse_loss(true, pred)) / torch.log(torch.tensor(10.0))


class Model():
    def __init__(self, opt):
        self.opt = opt
        self.device = self.opt.device

        train_dataloader, valid_dataloader = build_dataloader(opt)
        self.dataloader = {'train': train_dataloader, 'valid': valid_dataloader}

        self.net = ConvLSTM(input_dim=self.opt.channels,
                            hidden_dim=[16, 8],
                            kernel_size=(5, 5),
                            num_layers=2,
                            batch_first=True,
                            bias=True,
                            return_all_layers=True)
        self.net.to(self.device)
        self.mse_loss = nn.MSELoss()
        self.w_state = 1e-4
        if self.opt.pretrained_model:
            self.load_weight()
        self.optimizer = torch.optim.Adam(self.net.parameters(), self.opt.learning_rate)

    def train_epoch(self, epoch):
        print("--------------------start training epoch %2d--------------------" % epoch)
        hidden_state = None
        for sample_id, sample in enumerate(self.dataloader['train']):
            self.net.zero_grad()
            images, actions = sample
            # print(actions)
            # actions, images = images
            # print(actions[0])
            # images = images.permute([1, 0, 2, 3, 4])  ## T * N * C * H * W
            # actions = actions.permute([1, 0, 2])  ## T * N  * C
            images.requires_grad = True
            # images, actions = torch.autograd.Variable(images), torch.autograd.Variable(actions)
            gen_images, hidden_state = self.net(images, hidden_state)
            print(len(gen_images))
            loss, psnr = 0.0, 0.0
            for i, (image, gen_image) in enumerate(
                    zip(images[self.opt.context_frames:], gen_images[self.opt.context_frames - 1:])):
                print(len(gen_image))
                recon_loss = self.mse_loss(image, gen_image)
                psnr_i = peak_signal_to_noise_ratio(image, gen_image)
                loss += recon_loss
                psnr += psnr_i

            loss /= torch.tensor(self.opt.sequence_length - self.opt.context_frames)
            loss.requires_grad = True
            # print(loss.requires_grad)
            loss.backward()
            self.optimizer.step()

            loss.detach()

            if sample_id % self.opt.print_interval == 0:
                print("training epoch: %3d, iterations: %3d/%3d loss: %6f" %
                      (epoch, sample_id, 30, loss))

    def train(self):
        for epoch_i in range(0, self.opt.epochs):
            self.train_epoch(epoch_i)
            self.evaluate(epoch_i)
            self.save_weight(epoch_i)

    def evaluate(self, epoch):
        with torch.no_grad():
            recon_loss, state_loss = 0.0, 0.0
            for iter_, (images, actions, states) in enumerate(self.dataloader['valid']):
                images = images.permute([1, 0, 2, 3, 4]).unbind(0)
                actions = actions.permute([1, 0, 2]).unbind(0)
                states = states.permute([1, 0, 2]).unbind(0)
                gen_images, gen_states = self.net(images, actions, states[0])
                for i, (image, gen_image) in enumerate(
                        zip(images[self.opt.context_frames:], gen_images[self.opt.context_frames - 1:])):
                    recon_loss += self.mse_loss(image, gen_image)

                for i, (state, gen_state) in enumerate(
                        zip(states[self.opt.context_frames:], gen_states[self.opt.context_frames - 1:])):
                    state_loss += self.mse_loss(state, gen_state) * self.w_state
            recon_loss /= (torch.tensor(self.opt.sequence_length - self.opt.context_frames) * len(
                self.dataloader['valid'].dataset) / self.opt.batch_size)
            state_loss /= (torch.tensor(self.opt.sequence_length - self.opt.context_frames) * len(
                self.dataloader['valid'].dataset) / self.opt.batch_size)

            print("evaluation epoch: %3d, recon_loss: %6f, state_loss: %6f" % (epoch, recon_loss, state_loss))

    def save_weight(self, epoch):
        torch.save(self.net.state_dict(), os.path.join(self.opt.output_dir, "net_epoch_%d.pth" % epoch))

    def load_weight(self):
        self.net.load_state_dict(torch.load(self.opt.pretrained_model))
