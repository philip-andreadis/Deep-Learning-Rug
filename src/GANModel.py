import torch
import torch.nn as nn
from torch import optim

from models.Discriminator import PatchDiscriminator
from models.Generator import Generator

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

""" A class for combining the Generator and Discriminator models and train them alternately.

Attributes
----------
gen : <class nn.Module>
    The GAN's generator
disc : <class nn.Module>
    The GAN's discriminator
opt_G : <class optim.Adam>
    The optimizer for the Generator
opt_D : <class optim.Adam>
    The optimizer for the Discriminator

Methods
-------
optimize():
    Given the input and target data, performs one round of training on the generator and discriminator models
"""


class GANLoss(nn.Module):
    def __init__(self, real_label=1.0, fake_label=0.0):
        super().__init__()

        self.register_buffer('real_label', torch.tensor(real_label))
        self.register_buffer('fake_label', torch.tensor(fake_label))
        self.loss = nn.BCELoss()

    def get_labels(self, predictions, target_is_real):
        if target_is_real:
            labels = self.real_label
        else:
            labels = self.fake_label

        return labels.expand_as(predictions)

    def __call__(self, predictions, target_is_real):
        labels = self.get_labels(predictions, target_is_real)
        loss = self.loss(predictions, labels)
        return loss


def set_requires_grad(model, requires_grad=True):
    for p in model.parameters():
        p.requires_grad = requires_grad


class ColorizationGAN(nn.Module):
    """ Class initialization method. Initialize Generator, Discriminator, and optimizers.

    Arguments
    ----------
    device : <class 'torch.device'>
        CPU or CUDA selected device
    lr_g : <class 'float'>
        the learning rate for the Generator parameters
    lr_d : <class 'float'>
        the learning rate for the Discriminator parameters
    beta1 : <class 'float'>
        the first beta parameter for the Adam optimizer
    beta2 : <class 'float'>
        the second beta parameter for the Adam optimizer
    lambda_l1: <class 'float'>
        the factor by which the L1 loss is scaled before adding it to the GAN's loss
    pretrained : <class 'bool'>
        boolean to control whether to generate a pretrained ResNet encoder or a U-Net encoder from scratch
    """

    def __init__(self, device, lr_g=0.0002, lr_d=0.0002, beta1=0.5, beta2=0.999, lambda_l1=100, pretrained=True):
        super().__init__()

        self.device = device
        self.lambda_l1 = lambda_l1
        # Instantiate the Generator network
        self.gen = Generator(pretrained)

        # Initialize the weights of the Generator
        if not pretrained:
            self.gen.encoder_net.weight_init(mean=0.0, std=0.02)
        self.gen.decoder_net.weight_init(mean=0.0, std=0.02)
        self.gen = self.gen.to(device)

        # Instantiate the Discriminator network and initialize its weights
        self.disc = PatchDiscriminator()
        self.disc.weight_init(mean=0.0, std=0.02)
        self.disc = self.disc.to(device)

        # Instantiate the losses
        self.GANloss = GANLoss().to(self.device)
        self.L1Loss = nn.L1Loss()

        # Instantiate Adam optimizers
        self.opt_G = optim.Adam(self.gen.parameters(), lr=lr_g, betas=(beta1, beta2))
        self.opt_D = optim.Adam(self.disc.parameters(), lr=lr_d, betas=(beta1, beta2))

    def optimize(self, L, ab):
        """ Performs one round of training on a batch of images in the Lab colorspace.

        Arguments
        ----------
        L : <class 'Tensor'>
            the L channel of the image
        ab : <class 'Tensor'>
            the real ab channels of the image

        Returns
        -------
        loss_D : The loss for the Discriminator (fake + real)
        loss_G : The loss for the Generator (GANloss + L1)
        """

        # Get color channels from Generator
        fake_ab = self.gen(L)

        # Reshape L to a single channel for the discriminator
        L = torch.reshape(L[:, 0, :, :], (L.shape[0], 1, L.shape[2], L.shape[3]))

        self.disc.train()
        set_requires_grad(self.disc, True)
        self.disc.zero_grad()

        # Compose fake images and pass them to the Discriminator
        fake_image = torch.cat([L, fake_ab], dim=1)
        fake_predictions = self.disc(fake_image.detach())
        self.loss_D_fake = self.GANloss(fake_predictions, False)

        # Pass the real images to the Discriminator
        real_image = torch.cat([L, ab], dim=1)
        real_predictions = self.disc(real_image)
        self.loss_D_real = self.GANloss(real_predictions, True)

        # Combine losses and calculate the gradients
        self.loss_D = (self.loss_D_fake + self.loss_D_real) * 0.5

        # Update the Discriminator parameters
        self.loss_D.backward()
        self.opt_D.step()

        self.gen.train()
        set_requires_grad(self.disc, False)
        self.opt_G.zero_grad()

        # Combine the "reward signal" from the Discriminator with L1 loss
        fake_predictions = self.disc(fake_image)
        self.loss_G_GAN = self.GANloss(fake_predictions, True)
        self.loss_G_L1 = self.L1Loss(fake_ab, ab) * self.lambda_l1
        self.loss_G = self.loss_G_GAN + self.loss_G_L1

        # Update the parameters of the Generator
        self.loss_G.backward()
        self.opt_G.step()

    def test(self, L, ab):
        """ Passes the input through the GAN in test mode.

        Arguments
        ----------
        L : <class 'Tensor'>
            the L channel of the image
        ab : <class 'Tensor'>
            the real ab channels of the image

        Returns
        -------
        loss_D : The loss for the Discriminator (fake + real)
        loss_G : The loss for the Generator (GANloss + L1)
        fake_image : The images generated by the GAN
        """

        self.gen.eval()
        self.disc.eval()

        with torch.no_grad:
            # Get color channels from Generator
            fake_ab = self.gen(L)
            # Reshape L to a single channel for the discriminator
            L = torch.reshape(L[:, 0, :, :], (L.shape[0], 1, L.shape[2], L.shape[3]))
            # Compose fake images and pass them to the Discriminator
            fake_image = torch.cat([L, fake_ab], dim=1)
            fake_predictions = self.disc(fake_image.detach())
            loss_D_fake = self.GANloss(fake_predictions, False)
            # Pass the real images to the Discriminator
            real_image = torch.cat([L, ab], dim=1)
            real_predictions = self.disc(real_image)
            loss_D_real = self.GANloss(real_predictions, True)
            # Combine losses and calculate the gradients
            loss_D = (loss_D_fake + loss_D_real) * 0.5

            # Combine the "reward signal" from the Discriminator with L1 loss
            fake_predictions = self.disc(fake_image)
            loss_G_GAN = self.GANloss(fake_predictions, True)
            loss_G_L1 = self.L1Loss(fake_ab, ab) * self.lambda_L1
            loss_G = loss_G_GAN + loss_G_L1

        self.loss_D_real = loss_D_real
        self.loss_D_fake = loss_D_fake
        self.loss_D = loss_D,
        self.loss_G_GAN = loss_G_GAN,
        self.loss_G_L1 = loss_G_L1,
        self.loss_G = loss_G

        return fake_image

    def generate(self, L):
        """ Colorize black and white images, for cases where the real a and b channels are not present,
        -> the function you would use if you wanted to serve it in an application.

        Arguments
        ---------
        L : <class 'Tensor'>
            the L channel of the image

        Returns
        -------
        fake_image : The images generated by the GAN
        """

        L = L.to(device)

        self.gen.eval()
        with torch.no_grad():
            # Get color channels from Generator
            fake_ab = self.gen(L)
        return fake_ab
