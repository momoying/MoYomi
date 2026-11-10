"""CPU/GPU选择与失败回退；不将有NVIDIA驱动等同于模型能正常推理。"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading
import sys
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from module.ocr import create_ocr


class OcrBackendTests(TestCase):
    def setUp(self):
        create_ocr.cache_clear()
        self.addCleanup(create_ocr.cache_clear)
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.models = Path(folder)
        for name in ('ch_PP-OCRv4_det_infer', 'ch_PP-OCRv4_rec_infer', 'ch_ppocr_mobile_v2.0_cls_infer'):
            (self.models / name).mkdir()
            for filename in ('inference.pdmodel', 'inference.pdiparams'):
                (self.models / name / filename).write_bytes(b'test-model')
        self.engine = Mock()
        self.factory = Mock(return_value=self.engine)
        self.paddle = SimpleNamespace(is_compiled_with_cuda=Mock(return_value=False),
            device=SimpleNamespace(cuda=SimpleNamespace(device_count=Mock(return_value=0))))
        self.logger = Mock()
        self.enterContext(patch('module.model_paths.OCR_MODEL_DIR', self.models))
        self.enterContext(patch('module.ocr._cuda_dll_directories', return_value=()))
        self.enterContext(patch('module.logging.TaskLogger', return_value=self.logger))
        self.enterContext(patch.dict(sys.modules, {'paddle': self.paddle,
                                                 'paddleocr': SimpleNamespace(PaddleOCR=self.factory)}))

    def gpu(self):
        self.paddle.is_compiled_with_cuda.return_value = True
        self.paddle.device.cuda.device_count.return_value = 1

    def test_cpu_package_never_queries_cuda_or_runs_gpu_warmup(self):
        self.assertIs(create_ocr(cpu_acceleration=True), self.engine)
        self.paddle.device.cuda.device_count.assert_not_called()
        self.assertFalse(self.factory.call_args.kwargs['use_gpu'])
        self.assertTrue(self.factory.call_args.kwargs['enable_mkldnn'])
        self.assertEqual(self.factory.call_args.kwargs['cpu_threads'], 4)
        self.engine.ocr.assert_not_called()

    def test_gpu_requires_successful_detection_and_recognition_warmup(self):
        self.gpu()
        self.assertIs(create_ocr(cpu_acceleration=True), self.engine)
        self.assertTrue(self.factory.call_args.kwargs['use_gpu'])
        self.assertNotIn('enable_mkldnn', self.factory.call_args.kwargs)
        self.assertEqual(self.engine.ocr.call_count, 2)
        self.assertEqual(self.engine.ocr.call_args_list[0].kwargs, {'cls': False})
        self.assertEqual(self.engine.ocr.call_args_list[1].kwargs, {'cls': False, 'det': False})

    def test_no_gpu_or_driver_failure_uses_cpu(self):
        self.paddle.is_compiled_with_cuda.return_value = True
        create_ocr()
        self.assertFalse(self.factory.call_args.kwargs['use_gpu'])
        self.paddle.device.cuda.device_count.side_effect = RuntimeError('driver unavailable')
        create_ocr.cache_clear()
        create_ocr()
        self.assertFalse(self.factory.call_args.kwargs['use_gpu'])
        self.logger.warning.assert_called_once()

    def test_gpu_constructor_and_warmup_failures_both_fall_back(self):
        self.gpu()
        for warmup in (False, True):
            with self.subTest(warmup=warmup):
                create_ocr.cache_clear()
                gpu, cpu = Mock(), Mock()
                if warmup:
                    gpu.ocr.side_effect = RuntimeError('cuDNN unavailable')
                    self.factory.side_effect = [gpu, cpu]
                else:
                    self.factory.side_effect = [RuntimeError('CUDA unavailable'), cpu]
                self.assertIs(create_ocr(cpu_acceleration=True), cpu)
                self.assertFalse(self.factory.call_args.kwargs['use_gpu'])
                self.assertTrue(self.factory.call_args.kwargs['enable_mkldnn'])
                cpu.ocr.assert_not_called()

    def test_missing_model_is_reported_before_loading_any_backend(self):
        (self.models / 'ch_PP-OCRv4_rec_infer/inference.pdiparams').unlink()
        with self.assertRaisesRegex(FileNotFoundError, '模型缺失'):
            create_ocr()
        self.factory.assert_not_called()

    def test_cpu_comparison_can_explicitly_disable_gpu_and_other_tasks_keep_cpu_options(self):
        self.gpu()
        create_ocr(prefer_gpu=False)
        self.paddle.device.cuda.device_count.assert_not_called()
        self.assertFalse(self.factory.call_args.kwargs['use_gpu'])
        self.assertNotIn('enable_mkldnn', self.factory.call_args.kwargs)

    def test_cpu_engine_survives_tool_module_reload(self):
        from ui_app.pages.tools import ToolsPageMixin

        ui = ToolsPageMixin()
        first = ui._load_tool_module('super_oni')
        self.assertIs(first.local_ocr(), self.engine)
        second = ui._load_tool_module('super_oni')
        self.assertIsNot(first, second)
        self.assertIs(second.local_ocr(), self.engine)
        self.factory.assert_called_once()
        self.assertFalse(self.factory.call_args.kwargs['use_gpu'])
        self.assertTrue(self.factory.call_args.kwargs['enable_mkldnn'])

    def test_gpu_engine_only_initializes_and_warms_up_once(self):
        self.gpu()
        first = create_ocr(cpu_acceleration=True)
        self.assertIs(create_ocr(cpu_acceleration=True), first)
        self.factory.assert_called_once()
        self.assertEqual(first.ocr.call_count, 2)

    def test_two_tool_threads_share_one_initialization(self):
        from ui_app.pages.tools import ToolsPageMixin

        first = ToolsPageMixin()._load_tool_module('super_oni')
        second = ToolsPageMixin()._load_tool_module('super_oni')
        entered, release, second_started = threading.Event(), threading.Event(), threading.Event()

        def initialize(**kwargs):
            entered.set()
            if not release.wait(3):
                raise TimeoutError('test initialization release missing')
            return self.engine

        def second_call():
            second_started.set()
            return second.local_ocr()

        self.factory.side_effect = initialize
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(first.local_ocr)
            try:
                self.assertTrue(entered.wait(2))
                b = pool.submit(second_call)
                self.assertTrue(second_started.wait(2))
                self.assertEqual(self.factory.call_count, 1)
            finally:
                release.set()
            self.assertIs(a.result(timeout=3), self.engine)
            self.assertIs(b.result(timeout=3), self.engine)
        self.factory.assert_called_once()

    def test_gpu_failure_reuses_cpu_fallback_without_retrying_gpu(self):
        self.gpu()
        self.factory.side_effect = [RuntimeError('CUDA unavailable'), self.engine]
        self.assertIs(create_ocr(cpu_acceleration=True), self.engine)
        self.assertIs(create_ocr(cpu_acceleration=True), self.engine)
        self.assertEqual(self.factory.call_count, 2)
        self.logger.warning.assert_called_once()

    def test_different_cpu_gpu_options_keep_separate_engines(self):
        self.gpu()
        cpu, gpu = Mock(), Mock()
        self.factory.side_effect = [cpu, gpu]
        self.assertIs(create_ocr(prefer_gpu=False), cpu)
        self.assertIs(create_ocr(prefer_gpu=True), gpu)
        self.assertIs(create_ocr(prefer_gpu=False), cpu)
        self.assertIs(create_ocr(prefer_gpu=True), gpu)
        self.assertEqual(self.factory.call_count, 2)

    def test_initialization_exception_is_not_cached(self):
        self.factory.side_effect = [RuntimeError('temporary initialization failure'), self.engine]
        with self.assertRaisesRegex(RuntimeError, 'temporary initialization failure'):
            create_ocr()
        self.assertIs(create_ocr(), self.engine)
        self.assertIs(create_ocr(), self.engine)
        self.assertEqual(self.factory.call_count, 2)
