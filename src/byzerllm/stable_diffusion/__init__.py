import json
import time
import traceback
from typing import Dict, List

from byzerllm.stable_diffusion.api.models.diffusion import (
    HiresfixOptions,
    ImageGenerationOptions,
    MultidiffusionOptions,
)

from byzerllm.stable_diffusion.model import DiffusersModel

# model_name = "runwayml/stable-diffusion-v1-5"


def stream_chat(
    self,
    tokenizer,
    ins: str,
    his: List[Dict[str, str]] = [],
    max_length: int = 4090,
    top_p: float = 0.95,
    temperature: float = 0.1,
    **kwargs,
):
    prompt = ins
    negative_prompt = kwargs.get("negatvie_prompt", "")
    sampler_name = kwargs.get("sampler_name", "euler_a")
    sampling_steps = int(kwargs.get("sampling_steps", 25))
    batch_size = int(kwargs.get("batch_size", 1))
    batch_count = int(kwargs.get("batch_count", 1))
    cfg_scale = float(kwargs.get("cfg_scale", 7.5))
    seed = int(kwargs.get("seed", -1))
    width = int(kwargs.get("width", 768))
    height = int(kwargs.get("height", 768))
    enable_hires = "true" == kwargs.get("enable_hires", "false")
    enable_multidiff = "true" == kwargs.get("enable_multidiff", "false")
    upscaler_mode = kwargs.get("upscaler_mode", "bilinear")
    scale_slider = float(kwargs.get("scale_slider", 1.5))
    views_batch_size = int(kwargs.get("views_batch_size", 4))
    window_size = int(kwargs.get("window_size", 64))
    stride = int(kwargs.get("stride", 16))
    init_image = kwargs.get("init_image", None)
    strength = float(kwargs.get("strength", 0.5))

    # TODO: init_image format change
    images = generate_image(
        self,
        prompt=prompt,
        negative_prompt=negative_prompt,
        sampler_name=sampler_name,
        sampling_steps=sampling_steps,
        batch_size=batch_size,
        batch_count=batch_count,
        cfg_scale=cfg_scale,
        seed=seed,
        width=width,
        height=height,
        enable_hires=enable_hires,
        enable_multidiff=enable_multidiff,
        upscaler_mode=upscaler_mode,
        scale_slider=scale_slider,
        views_batch_size=views_batch_size,
        window_size=window_size,
        stride=stride,
        init_image=init_image,
        strength=strength,
    )
    content = json.dumps([{"prompt": i[0], "img64": i[1]} for i in images])
    return [(content, "")]


def init_model(
    model_dir, infer_params: Dict[str, str] = {}, sys_conf: Dict[str, str] = {}
):
    # device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # # all params from infer_params can set in method from_pretrained
    # model = StableDiffusionPipeline.from_pretrained(model_name, torch_dtype=torch.float16)
    # model.to(device)
    # import types
    # model.stream_chat = types.MethodType(stream_chat, model)
    # return (model, None)
    model = DiffusersModel(model_dir)
    model.activate()
    import types

    model.stream_chat = types.MethodType(stream_chat, model)
    return (model, None)


# sampler_name SCHEDULERS.keys()
# samping_steps min=1,max=100
# batch_size min=1,max=50
# batch_count min=1,max=50
# cfg_scale min=1, max=20,
# seed default=-1
# width min=64,max=2048
# height min=64,max=2048
# scale_slider min=1,max=4
def generate_image(
    model,
    prompt,
    negative_prompt,
    sampler_name="euler_a",
    sampling_steps=25,
    batch_size=1,
    batch_count=1,
    cfg_scale=7.5,
    seed=-1,
    width=768,
    height=768,
    enable_hires=False,
    enable_multidiff=False,
    upscaler_mode="bilinear",
    scale_slider=1.5,
    views_batch_size=4,
    window_size=64,
    stride=16,
    init_image=None,
    strength=0.5,
):
    hiresfix = HiresfixOptions(
        enable=enable_hires, mode=upscaler_mode, scale=scale_slider
    )

    multidiffusion = MultidiffusionOptions(
        enable=enable_multidiff,
        views_batch_size=views_batch_size,
        window_size=window_size,
        stride=stride,
    )

    opts = ImageGenerationOptions(
        prompt=prompt,
        negative_prompt=negative_prompt,
        batch_size=batch_size,
        batch_count=batch_count,
        scheduler_id=sampler_name,
        num_inference_steps=sampling_steps,
        guidance_scale=cfg_scale,
        height=height,
        width=width,
        strength=strength,
        seed=seed,
        image=init_image,
        hiresfix=hiresfix,
        multidiffusion=multidiffusion,
    )

    count = 0

    if opts.hiresfix.enable:
        inference_steps = opts.num_inference_steps + int(
            opts.num_inference_steps * opts.strength
        )
    else:
        inference_steps = opts.num_inference_steps

    start = time.perf_counter()

    try:
        for data in model(opts, {}):
            if type(data) == tuple:
                step, preview = data
                progress = step / (opts.batch_count * inference_steps)
                previews = []
                for images, opts in preview:
                    previews.extend(images)

                if len(previews) == count:
                    pass
                else:
                    count = len(previews)

                print(f"Progress: {progress * 100:.2f}%, Step: {step}")
            else:
                image = data

        end = time.perf_counter()

        results = []
        for images, opts in image:
            for i in images:
                results.extend(i)

        print(f"Finished in {end -start:0.4f} seconds")
        yield results
    except Exception as e:
        traceback.print_exc()
        yield []
