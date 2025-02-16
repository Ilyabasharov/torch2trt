from torch2trt.torch2trt import *
from torch2trt.module_test import add_module_test


@tensorrt_converter('torch.nn.functional.avg_pool1d')
def convert_avg_pool1d(ctx):
    # At the time of this implementation, TensorRT 8.x does not yet support avg pooling in 1D using `add_pooling_nd(...)`.
    # As such, we use a workaround here, by unsqueezing another dimension into the input (thus transforming it from
    # (N, C, L) to (N, C, L, 1)) so that we can use 2D max pooling across the last three dimensions.

    input = get_arg(ctx, 'input', pos=0, default=None)
    input_trt = trt_(ctx.network, input)
    output = ctx.method_return
    
    kernel_size = get_arg(ctx, 'kernel_size', pos=1, default=None)
    stride = get_arg(ctx, 'stride', pos=2, default=None)
    padding = get_arg(ctx, 'padding', pos=3, default=0)
    ceil_mode = get_arg(ctx, 'ceil_mode', pos=4, default=False)
    count_include_pad = get_arg(ctx, 'count_include_pad', pos=5, default=True)

    # Convert inputs to be 2d compatible as inputs will always be 1d.
    kernel_size = (kernel_size, 1)
    stride = kernel_size if not stride else (stride, 1)
    padding = (padding, 0)

    # Shuffle layer to unsqueeze another dimension for 2D max pooling.
    unsqueeze_layer = ctx.network.add_shuffle(input_trt)
    set_layer_precision(ctx, unsqueeze_layer)
    unsqueeze_layer.reshape_dims = tuple([*input_trt.shape, 1])
    unsqueeze_trt = unsqueeze_layer.get_output(0)

    # Use 2D max pooling here to fake 1D max pooling.
    layer = ctx.network.add_pooling_nd(
        input=unsqueeze_trt,
        type=trt.PoolingType.AVERAGE,
        window_size=kernel_size,
    )
    set_layer_precision(ctx, layer)
    layer.stride_nd = stride
    layer.padding_nd = padding
    layer.average_count_excludes_padding = not count_include_pad

    if ceil_mode:
        layer.padding_mode = trt.PaddingMode.EXPLICIT_ROUND_UP

    pooling_trt = layer.get_output(0)

    # Shuffle layer to squeeze out dimension that was just added for 2D max pooling so return is still in 1D.
    squeeze_layer = ctx.network.add_shuffle(pooling_trt)
    set_layer_precision(ctx, squeeze_layer)
    squeeze_layer.reshape_dims = tuple(pooling_trt.shape[:-1])
    output._trt = squeeze_layer.get_output(0)

@tensorrt_converter("torch.nn.functional.avg_pool2d", enabled=trt_version() < '7.0')
def convert_avg_pool2d(ctx):
    # parse args
    input = get_arg(ctx, "input", pos=0, default=None)
    kernel_size = get_arg(ctx, "kernel_size", pos=1, default=None)
    stride = get_arg(ctx, "stride", pos=2, default=None)
    padding = get_arg(ctx, "padding", pos=3, default=0)
    ceil_mode = get_arg(ctx, "ceil_mode", pos=4, default=False)
    count_include_pad = get_arg(ctx, "count_include_pad", pos=5, default=True)

    # get input trt tensor (or create constant if it doesn't exist)
    input_trt = add_missing_trt_tensors(ctx.network, [input])[0]

    output = ctx.method_return

    # get kernel size
    if not isinstance(kernel_size, tuple):
        kernel_size = (kernel_size,) * 2

    # get stride
    if not isinstance(stride, tuple):
        stride = (stride,) * 2

    # get padding
    if not isinstance(padding, tuple):
        padding = (padding,) * 2

    layer = ctx.network.add_pooling(
        input=input_trt, type=trt.PoolingType.AVERAGE, window_size=kernel_size
    )

    layer.stride = stride
    layer.padding = padding
    layer.average_count_excludes_padding = not count_include_pad

    if ceil_mode:
        layer.padding_mode = trt.PaddingMode.EXPLICIT_ROUND_UP

    output._trt = layer.get_output(0)


@tensorrt_converter('torch.nn.functional.avg_pool2d', enabled=trt_version() >= '7.0')
@tensorrt_converter('torch.nn.functional.avg_pool3d', enabled=trt_version() >= '7.0')
def convert_avg_pool_trt7(ctx):
    # parse args
    input = get_arg(ctx, 'input', pos=0, default=None)
    kernel_size = get_arg(ctx, 'kernel_size', pos=1, default=None)
    stride = get_arg(ctx, 'stride', pos=2, default=None)
    padding = get_arg(ctx, 'padding', pos=3, default=0)
    ceil_mode = get_arg(ctx, 'ceil_mode', pos=4, default=False)
    count_include_pad = get_arg(ctx, 'count_include_pad', pos=5, default=True)
    
    # get input trt tensor (or create constant if it doesn't exist)
    input_trt = add_missing_trt_tensors(ctx.network, [input])[0]
    output = ctx.method_return

    input_dim = input.dim() - 2

    # get kernel size
    if not isinstance(kernel_size, tuple):
        kernel_size = (kernel_size, ) * input_dim

    # get stride
    if not isinstance(stride, tuple):
        stride = (stride, ) * input_dim

    # get padding
    if not isinstance(padding, tuple):
        padding = (padding, ) * input_dim

    layer = ctx.network.add_pooling_nd(
        input=input_trt, type=trt.PoolingType.AVERAGE, window_size=kernel_size)
    
    layer.stride_nd = stride
    layer.padding_nd = padding
    layer.average_count_excludes_padding = not count_include_pad
    
    if ceil_mode:
        layer.padding_mode = trt.PaddingMode.EXPLICIT_ROUND_UP

    output._trt = layer.get_output(0)
    
    
@add_module_test(torch.float32, torch.device("cuda"), [(1, 3, 4, 6)])
@add_module_test(torch.float32, torch.device("cuda"), [(1, 3, 5, 7)])
def test_avg_pool2d_without_ceil_mode():
    return torch.nn.AvgPool2d(
        kernel_size=3, stride=2, padding=1, ceil_mode=False
    )


@add_module_test(torch.float32, torch.device("cuda"), [(1, 3, 4, 6)])
@add_module_test(torch.float32, torch.device("cuda"), [(1, 3, 5, 7)])
def test_avg_pool2d_with_ceil_mode():
    return torch.nn.AvgPool2d(
        kernel_size=3, stride=2, padding=1, ceil_mode=True, count_include_pad=False
    )  # TRT does not support ceil_mode=True && count_include_pad=True


@add_module_test(torch.float32, torch.device('cuda'), [(1, 3, 4, 4, 6)], enabled=trt_version() >= '7.0')
@add_module_test(torch.float32, torch.device('cuda'), [(1, 3, 3, 5, 7)], enabled=trt_version() >= '7.0')
def test_avg_pool3d_without_ceil_mode_trt7():
    return torch.nn.AvgPool3d(
        kernel_size=3, stride=2, padding=1, ceil_mode=False
    )


@add_module_test(torch.float32, torch.device('cuda'), [(1, 3, 4, 4, 6)], enabled=trt_version() >= '7.0')
@add_module_test(torch.float32, torch.device('cuda'), [(1, 3, 3, 5, 7)], enabled=trt_version() >= '7.0')
def test_avg_pool3d_with_ceil_mode_trt7():
    return torch.nn.AvgPool3d(
        kernel_size=3, stride=2, padding=1, ceil_mode=True, count_include_pad=False
    ) # TRT does not support ceil_mode=True && count_include_pad=True
