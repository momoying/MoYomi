"""本地PaddleOCR初始化：可用CUDA优先，否则保持CPU兼容。"""
from functools import lru_cache
import importlib.util
import os
import threading
from pathlib import Path

OCR_LOCK = threading.RLock()


@lru_cache(maxsize=1)
def _cuda_dll_directories():
    """Windows GPU可选依赖放在venv内，不修改系统CUDA安装或系统PATH。"""
    if os.name != 'nt':
        return ()
    spec = importlib.util.find_spec('nvidia')
    if spec is None:
        return ()
    directories = []
    for root in spec.submodule_search_locations or ():
        for name in ('cuda_runtime', 'cublas', 'cudnn'):
            folder = Path(root) / name / 'bin'
            if folder.is_dir():
                directories.append(str(folder))
    handles = tuple(os.add_dll_directory(folder) for folder in directories)
    if directories:
        os.environ['PATH'] = os.pathsep.join(directories + [os.environ.get('PATH', '')])
    return handles  # 保留句柄，避免目录注册被垃圾回收撤销。


@lru_cache(maxsize=4)
def create_ocr(*, cpu_acceleration=False, prefer_gpu=True):
    """同一进程内按 CPU/GPU 配置复用引擎，工具模块重新加载也不会丢失。"""
    from module.logging import TaskLogger
    from module.model_paths import OCR_MODEL_DIR

    for folder in ('ch_PP-OCRv4_det_infer', 'ch_PP-OCRv4_rec_infer', 'ch_ppocr_mobile_v2.0_cls_infer'):
        for filename in ('inference.pdmodel', 'inference.pdiparams'):
            if not (OCR_MODEL_DIR / folder / filename).is_file():
                raise FileNotFoundError(f'本地 OCR 模型缺失：{folder}/{filename}')
    _cuda_dll_directories()
    os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
    import paddle
    from paddleocr import PaddleOCR

    logger = TaskLogger('OCR')
    use_gpu = False
    if prefer_gpu:
        try:
            use_gpu = paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0
        except Exception as error:
            logger.warning('初始化', f'CUDA检测失败，使用CPU：{error}')
    options = dict(
        det_model_dir=str(OCR_MODEL_DIR / 'ch_PP-OCRv4_det_infer'),
        rec_model_dir=str(OCR_MODEL_DIR / 'ch_PP-OCRv4_rec_infer'),
        cls_model_dir=str(OCR_MODEL_DIR / 'ch_ppocr_mobile_v2.0_cls_infer'),
        lang='ch', show_log=False,
    )
    if use_gpu:
        try:
            import numpy as np
            engine = PaddleOCR(**options, use_gpu=True, gpu_id=0)
            # 真正执行检测和识别，确认cuDNN可用；不依赖nvidia-smi或仅“有显卡”。
            blank = np.full((64, 320, 3), 255, np.uint8)
            engine.ocr(blank, cls=False)
            engine.ocr(blank, cls=False, det=False)
            logger.info('初始化', '使用GPU：CUDA:0')
            return engine
        except Exception as error:
            logger.warning('初始化', f'GPU初始化或预热失败，回退CPU：{error}')
    if cpu_acceleration:
        options.update(enable_mkldnn=True, cpu_threads=4)
    engine = PaddleOCR(**options, use_gpu=False)
    logger.info('初始化', '使用CPU')
    return engine
