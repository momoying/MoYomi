from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from tasks.Merchant.assets import MerchantAssets
from tasks.Merchant import merchant
from tasks.Merchant.merchant import (
    MerchantResult,
    _classify_blue_ticket_price,
    _detect_blue_ticket_price,
)


class MerchantPriceTests(unittest.TestCase):
    def test_price_60_is_recognized_and_reported(self):
        template = cv2.imread(MerchantAssets.I_PRICE_60.path)
        self.assertIsNotNone(template)
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        height, width = template.shape[:2]
        frame[115 : 115 + height, 25 : 25 + width] = template

        with patch.object(merchant, "_get_ocr_engine", return_value=Mock(ocr=Mock(return_value=None))), patch.object(merchant, "print"):
            price, _ = _classify_blue_ticket_price(frame, (0, 0, 87, 88))

        self.assertEqual(price, "60")
        self.assertEqual(MerchantResult.BLUE_TICKET_60.value, "blue_ticket_60")

    def test_ocr_price_takes_precedence_over_templates(self):
        engine = Mock(ocr=Mock(return_value=[[['box', ('50', 0.91)]]]))
        frame = np.zeros((200, 200, 3), dtype=np.uint8)

        with patch.object(merchant, "_get_ocr_engine", return_value=engine), patch.object(
            merchant, "_load_cv_template", side_effect=AssertionError("template should not run"),
        ), patch.object(merchant, "print"):
            price, scores = _classify_blue_ticket_price(frame, (0, 0, 87, 88))

        self.assertEqual(price, "50")
        self.assertEqual(scores, {})
        self.assertEqual(engine.ocr.call_args.kwargs, {"cls": False})

    def test_template_fallback_accepts_highest_score_without_winner_margin(self):
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        score_values = [0.95, 0.949, 0.80, 0.79, 0.78]
        matches = [np.array([[score]], dtype=np.float32) for score in score_values]
        with patch.object(merchant, "_get_ocr_engine", return_value=Mock(ocr=Mock(return_value=None))), patch.object(
            merchant, "_load_cv_template", return_value=np.zeros((10, 50, 3), dtype=np.uint8),
        ), patch.object(merchant.cv2, "matchTemplate", side_effect=matches), patch.object(
            merchant, "print",
        ):
            price, _ = _classify_blue_ticket_price(frame, (0, 0, 87, 88))

        self.assertEqual(price, "50")

    def test_template_fallback_rejects_all_scores_below_threshold(self):
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        matches = [np.array([[0.93]], dtype=np.float32) for _ in range(5)]
        with patch.object(merchant, "_get_ocr_engine", return_value=Mock(ocr=Mock(return_value=None))), patch.object(
            merchant, "_load_cv_template", return_value=np.zeros((10, 50, 3), dtype=np.uint8),
        ), patch.object(merchant.cv2, "matchTemplate", side_effect=matches), patch.object(
            merchant, "print",
        ):
            price, _ = _classify_blue_ticket_price(frame, (0, 0, 87, 88))

        self.assertIsNone(price)

    def test_same_shelf_uses_one_readable_price_when_another_ticket_is_unknown(self):
        frame = np.zeros((300, 300, 3), dtype=np.uint8)
        tickets = [((0, 0, 87, 88), 0.91), ((100, 0, 187, 88), 0.90)]
        with patch.object(merchant, "_take_frame", return_value=frame), patch.object(
            merchant, "_find_blue_ticket_rects", return_value=tickets,
        ), patch.object(merchant, "_classify_blue_ticket_price", side_effect=[("60", {}), (None, {})]), patch.object(
            merchant, "print",
        ):
            found, price = _detect_blue_ticket_price(timeout=1.0)

        self.assertTrue(found)
        self.assertEqual(price, "60")

    def test_conflicting_prices_on_same_shelf_return_unknown(self):
        frame = np.zeros((300, 300, 3), dtype=np.uint8)
        tickets = [((0, 0, 87, 88), 0.91), ((100, 0, 187, 88), 0.90)]
        with patch.object(merchant, "_take_frame", return_value=frame), patch.object(
            merchant, "_find_blue_ticket_rects", return_value=tickets,
        ), patch.object(merchant, "_classify_blue_ticket_price", side_effect=[("60", {}), ("70", {})]), patch.object(
            merchant, "print",
        ):
            found, price = _detect_blue_ticket_price(timeout=1.0)

        self.assertTrue(found)
        self.assertIsNone(price)

    def test_merchant_price_failure_completes_without_refreshing_shop(self):
        with patch.object(merchant.utils, "connect_to_mumu"), patch.object(
            merchant, "_ensure_store_menu_expanded", return_value=True,
        ), patch.object(merchant, "_wait_and_click", return_value=True), patch.object(
            merchant, "_open_merchant_page", return_value=MerchantResult.NO_BLUE_TICKET,
        ), patch.object(merchant, "_detect_blue_ticket_price", return_value=(True, None)), patch.object(
            merchant, "_refresh_merchant_shop",
        ) as refresh, patch.object(merchant, "_return_to_courtyard", return_value=True), patch.object(
            merchant, "print",
        ):
            result = merchant.check_merchant()

        self.assertIs(result, MerchantResult.UNKNOWN_PRICE)
        refresh.assert_not_called()

    def test_50_blue_ticket_still_stops_merchant_scan(self):
        frame = np.zeros((300, 300, 3), dtype=np.uint8)
        tickets = [((0, 0, 87, 88), 0.91)]
        with patch.object(merchant, "_take_frame", return_value=frame), patch.object(
            merchant, "_find_blue_ticket_rects", return_value=tickets,
        ), patch.object(merchant, "_classify_blue_ticket_price", return_value=("50", {})), patch.object(
            merchant, "print",
        ):
            found, price = _detect_blue_ticket_price(timeout=1.0)

        self.assertTrue(found)
        self.assertEqual(price, "50")


if __name__ == "__main__":
    unittest.main()
