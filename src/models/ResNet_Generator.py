import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision.models import resnet18, ResNet18_Weights


class ResNetEncoder(nn.Module):
    """ Defines the ResNet-18 encoder for the Generator. """

    def __init__(self):
        super().__init__()

        self.resnet18 = resnet18(weights=ResNet18_Weights.IMAGENET1K_V1)

    def forward(self, x):
        self.init_layer = self.resnet18.conv1(x)
        self.init_layer = self.resnet18.bn1(self.init_layer)
        self.init_layer = self.resnet18.relu(self.init_layer)  # [64, H/2, W/2]

        self.block1 = self.resnet18.maxpool(self.init_layer)  # [64, H/4, W/4]
        self.block1 = self.resnet18.layer1(self.block1)  # [64, H/4, W/4]
        self.block2 = self.resnet18.layer2(self.block1)  # [128, H/8, W/8]
        self.block3 = self.resnet18.layer3(self.block2)  # [256, H/16, W/16]
        self.block4 = self.resnet18.layer4(self.block3)  # [512, H/32, W/32]

        return self.block4


class ResNetDecoder(nn.Module):
    """ Defines the ResNet decoder network for the Generator.

    Arguments
    ----------
    encoder_net : PyTorch model object of encoder
        the encoder network of the Generator
    """

    def __init__(self, encoder_net, out_channels=512, kernel_size=4, stride=2, padding=1, use_dropout=False):
        super().__init__()

        self.encoder_net = encoder_net

        self.up_block1 = self.transp_conv_block(512, out_channels // 2, kernel_size, stride, padding, use_dropout)
        self.up_block2 = self.transp_conv_block(out_channels, out_channels // 4, kernel_size, stride, padding, use_dropout)
        self.up_block3 = self.transp_conv_block(out_channels // 2, out_channels // 8, kernel_size, stride, padding, use_dropout)
        self.up_block4 = self.transp_conv_block(out_channels // 4, out_channels // 8, kernel_size, stride, padding, use_dropout)

        self.up_block5 = nn.ConvTranspose2d(out_channels // 4, 2, kernel_size=kernel_size, stride=stride, padding=padding)

    def forward(self, x):
        up_1 = self.up_block1(x)  # [256, H/16, W/16]
        up_1 = torch.cat([self.encoder_net.block3, up_1], dim=1)  # [512, H/16, W/16]

        up_2 = self.up_block2(up_1)  # [128, H/8, W/8]
        up_2 = torch.cat([self.encoder_net.block2, up_2], dim=1)  # [256, H/8, W/8]

        up_3 = self.up_block3(up_2)  # [64, H/4, W/4]
        up_3 = torch.cat([self.encoder_net.block1, up_3], dim=1)  # [128, H/4, W/4]

        up_4 = self.up_block4(up_3)  # [64, H/2, W/2]
        up_4 = torch.cat([self.encoder_net.init_layer, up_4], dim=1)  # [128, H/2, W/2]

        up_5 = self.up_block5(F.relu(up_4))  # [2, H, W]
        output_image = torch.tanh(up_5)

        return output_image

    @staticmethod
    def transp_conv_block(in_channels, out_channels, kernel_size, stride, padding, use_dropout):
        """ Builds a transposed convolutional block.

        Arguments
        ---------
        in_channels : <class 'int'>
            the number of input channels
        out_channels : <class 'int'>
            the number of output channels
        kernel_size : <class 'int'>
            the convolution kernel size
        stride : <class 'int'>
            the stride to be used for the transposed convolution
        padding : <class 'int'>
            the padding to be used for the transposed convolution
        use_dropout : bool (default=False)
            boolean to control whether to use dropout or not

        Returns
        -------
        A sequential block depending on the input arguments
        """

        if use_dropout:
            block = nn.Sequential(
                nn.ReLU(),
                nn.ConvTranspose2d(in_channels, out_channels, kernel_size=kernel_size, stride=stride, padding=padding, bias=False),
                nn.BatchNorm2d(out_channels),
                nn.Dropout(0.5),
            )
        else:
            block = nn.Sequential(
                nn.ReLU(),
                nn.ConvTranspose2d(in_channels, out_channels, kernel_size=kernel_size, stride=stride, padding=padding, bias=False),
                nn.BatchNorm2d(out_channels),
            )
        return block

    # Initialize decoder weights from a Gaussian distribution with mean 0 and std 0.02
    def weight_init(self, mean, std):
        for name, layer in self.named_modules():
            normal_init(layer, mean, std)


def normal_init(m, mean, std):
    if isinstance(m, nn.ConvTranspose2d) or isinstance(m, nn.Conv2d):
        m.weight.data.normal_(mean, std)
        if m.bias is not None:
            m.bias.data.zero_()
