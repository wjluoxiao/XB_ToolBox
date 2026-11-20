"""CPU regression tests for XB_OutpaintBoard; no ComfyUI installation or GPU needed.

Run: python -m unittest discover -s tests -p 'test_outpaint_board_geometry.py' -v
Requires torch only (the node module deliberately avoids ComfyUI imports).
"""
import importlib.util
from pathlib import Path
import unittest

import torch


def load_module():
    path = Path(__file__).resolve().parents[1] / 'nodes' / 'image' / 'nodes_outpaint_board.py'
    spec = importlib.util.spec_from_file_location('xb_outpaint_board', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BOARD = load_module()


class BoardSizeTests(unittest.TestCase):
    def test_preset_ratio_links_the_other_side(self):
        # 16:9 给宽 1536 → 高 864；9:16 给高 1536 → 宽 864
        self.assertEqual(BOARD.board_size('16:9 (Widescreen)', 1536, 1024, 16), (1536, 864))
        self.assertEqual(BOARD.board_size('9:16 (Portrait Widescreen)', 1024, 1536, 16), (864, 1536))

    def test_bigger_side_drives_like_params_master(self):
        # 与「XB-BOX - 🖼️ 图片参数大全」一致：w >= h 用宽推高，否则用高推宽
        self.assertEqual(BOARD.board_size('1:1 (Square)', 1024, 768, 16), (1024, 1024))
        self.assertEqual(BOARD.board_size('1:1 (Square)', 768, 1024, 16), (1024, 1024))
        self.assertEqual(BOARD.board_size('16:9 (Widescreen)', 1024, 1024, 16), (1024, 576))
        self.assertEqual(BOARD.board_size('9:16 (Portrait Widescreen)', 1024, 1024, 16), (1024, 1824))

    def test_custom_ratio_keeps_both_sides(self):
        # 自定义不联动：填多少就是多少（竖图也能填）
        self.assertEqual(BOARD.board_size('自定义', 1024, 768, 16), (1024, 768))
        self.assertEqual(BOARD.board_size('自定义', 768, 1024, 16), (768, 1024))

    def test_every_side_is_a_multiple(self):
        for multiple in (8, 16, 32, 64):
            for ratio in BOARD.ASPECT_RATIOS:
                width, height = BOARD.board_size(ratio, 1000, 700, multiple)
                self.assertEqual(width % multiple, 0, (ratio, multiple, width))
                self.assertEqual(height % multiple, 0, (ratio, multiple, height))

    def test_multiple_is_clamped_to_supported_range(self):
        self.assertEqual(BOARD._multiple(2), 8)
        self.assertEqual(BOARD._multiple(1000), 128)


class PlacementTests(unittest.TestCase):
    def test_auto_fit_never_upscales_the_source(self):
        # 512 的图放进 1024 画布：保持 512、居中，不去放大原图
        self.assertEqual(BOARD.placement(None, 1024, 1024, 512, 512, 16),
                         (256, 256, 512, 512))

    def test_auto_fit_contains_and_snaps(self):
        x, y, w, h = BOARD.placement(None, 1536, 864, 1024, 1024, 16)
        self.assertEqual((x, y, w, h), (336, 0, 864, 864))

    def test_layout_values_are_applied(self):
        # layout 是「所见即所得」：不再为了凑对齐倍数去改用户的摆放
        layout = {"s": 0.5, "cx": 0.5, "cy": 0.5}
        x, y, w, h = BOARD.placement(layout, 1536, 864, 1024, 1024, 32)
        self.assertEqual((x, y, w, h), (384, 48, 768, 768))

    def test_auto_fit_always_fits_inside_the_canvas(self):
        # 自动摆放 = contain：整图完整落在画布内（尺寸向下取整，吸附后也不会溢出）
        for canvas in ((1024, 1024), (1536, 864), (864, 1536), (2048, 512)):
            for image in ((1024, 1024), (704, 1024), (3000, 700), (64, 64)):
                x, y, w, h = BOARD.placement(None, canvas[0], canvas[1], image[0], image[1], 16)
                self.assertGreaterEqual(x, 0, (canvas, image))
                self.assertGreaterEqual(y, 0, (canvas, image))
                self.assertLessEqual(x + w, canvas[0], (canvas, image))
                self.assertLessEqual(y + h, canvas[1], (canvas, image))

    def test_image_may_overflow_the_canvas(self):
        # 允许拖出画布（= 裁剪），但尺寸有 4 倍上限
        capped = BOARD.placement({"s": 10.0, "cx": 0.5, "cy": 0.5}, 1024, 1024, 512, 512, 8)
        self.assertEqual(capped[2:], (1024 * BOARD.SCALE_FACTOR_MAX, 1024 * BOARD.SCALE_FACTOR_MAX))

    def test_at_least_one_real_corner_stays_inside(self):
        # 任何摆放状态下，图片至少有一个真实角落在画布内（离边 ≥ 一个对齐倍数），
        # 四角调节点（贴在真实四角上）才永远抓得到；同时所有数值保持对齐。
        layouts = [{"s": s, "cx": cx, "cy": cy}
                   for s in (0.2, 0.5, 1.0, 1.7, 3.0)
                   for cx in (-9, -1, 0.5, 3, 9)
                   for cy in (-9, -1, 0.5, 3, 9)]
        for canvas in ((1024, 1024), (1536, 864), (864, 1536)):
            for layout in layouts:
                m = 16
                x, y, w, h = BOARD.placement(layout, canvas[0], canvas[1], 704, 1024, m)
                corners = [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]
                self.assertTrue(
                    any(0 <= px <= canvas[0] and 0 <= py <= canvas[1] for px, py in corners),
                    (canvas, layout, x, y, w, h),
                )

    def test_contain_has_no_gap_on_the_limiting_axis(self):
        # 居中填满 / 自动摆放 = contain：长边方向必须严丝合缝，不能为了凑齐倍数留空隙
        # 2048² 进 16:9、长边 1024 的画布（1024×576）：正好 576²，上下无空隙
        self.assertEqual(BOARD.placement(None, 1024, 576, 2048, 2048, 16), (224, 0, 576, 576))
        # 704×1024 进同一张画布：高度必须贴满 576（以前被 floor 到 544，上下各留 16px）
        x, y, w, h = BOARD.placement(None, 1024, 576, 704, 1024, 16)
        self.assertEqual(h, 576)
        self.assertEqual(y, 0)
        self.assertLessEqual(x + w, 1024)

    def test_garbage_layout_falls_back_to_auto(self):
        for bad in ('', 'not json', '{}', '{"s": 0, "cx": 0.5, "cy": 0.5}',
                    '{"s": "x", "cx": 0.5, "cy": 0.5}', '[1,2,3]', None):
            self.assertIsNone(BOARD.parse_layout(bad))
            self.assertEqual(BOARD.placement(BOARD.parse_layout(bad), 1024, 1024, 512, 512, 16),
                             (256, 256, 512, 512))


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.node = BOARD.XB_OutpaintBoard()
        # 512x512 全红，画布 1:1 1024 → 摆放矩形正好 512x512，不触发重采样
        self.image = torch.zeros((1, 512, 512, 3))
        self.image[..., 0] = 1.0

    def render(self, **kwargs):
        out = self.node.render(**kwargs)
        self.assertIsInstance(out, dict)          # 带 ui 预览的标准返回结构
        self.assertIn("result", out)
        result = out["result"]
        self.assertEqual(len(result), 3)          # 图像 / 遮罩 / 接缝信息
        return result[:2]

    def board_result(self, **kwargs):
        return self.node.render(**kwargs)["result"]

    def test_output_is_canvas_sized_with_gray_padding(self):
        image, mask = self.render(aspect_ratio='1:1 (Square)', width=1024, height=1024,
                                  multiple=16, image=self.image)
        self.assertEqual(tuple(image.shape), (1, 1024, 1024, 3))
        self.assertEqual(tuple(mask.shape), (1, 1024, 1024))
        self.assertAlmostEqual(float(image[0, 0, 0, 0]), 128 / 255, places=6)
        self.assertEqual(float(mask[0, 0, 0]), 1.0)          # 外补区 = 1

    def test_fill_color_is_applied(self):
        image, _ = self.render(aspect_ratio='1:1 (Square)', width=1024, height=1024,
                               multiple=16, fill_color="#FF0080", image=self.image)
        self.assertAlmostEqual(float(image[0, 0, 0, 0]), 1.0, places=6)
        self.assertAlmostEqual(float(image[0, 0, 0, 1]), 0.0, places=6)
        self.assertAlmostEqual(float(image[0, 0, 0, 2]), 128 / 255, places=6)
        # 非法颜色回落到中性灰
        gray, _ = self.render(aspect_ratio='1:1 (Square)', width=1024, height=1024,
                              multiple=16, fill_color="oops", image=self.image)
        self.assertAlmostEqual(float(gray[0, 0, 0, 0]), 128 / 255, places=6)

    def test_untouched_pixels_are_copied_verbatim(self):
        image, mask = self.render(aspect_ratio='1:1 (Square)', width=1024, height=1024,
                                  multiple=16, image=self.image)
        pasted = image[0, 256:768, 256:768, :]
        self.assertTrue(torch.equal(pasted, self.image[0]))  # 非缩放路径必须逐位相同
        self.assertEqual(float(mask[0, 256:768, 256:768].max()), 0.0)

    def test_input_mask_is_unioned_into_output_mask(self):
        inner = torch.zeros((1, 512, 512))
        inner[0, 100:200, 100:200] = 1.0
        _, mask = self.render(aspect_ratio='1:1 (Square)', width=1024, height=1024,
                              multiple=16, image=self.image, mask=inner)
        self.assertEqual(float(mask[0, 356, 356]), 1.0)      # 图片内 100..200 偏移 256
        self.assertEqual(float(mask[0, 300, 300]), 0.0)

    def test_layout_controls_where_the_image_lands(self):
        layout = '{"v":1,"s":0.25,"cx":0.25,"cy":0.25}'
        image, mask = self.render(aspect_ratio='1:1 (Square)', width=1024, height=1024,
                                 multiple=16, layout=layout, image=self.image)
        self.assertEqual(float(image[0, 128, 128, 0]), 1.0)  # s=0.25 → 256 宽，中心 256
        self.assertEqual(float(mask[0, 128, 128]), 0.0)
        self.assertEqual(float(mask[0, 700, 700]), 1.0)

    def test_missing_image_returns_blank_board(self):
        image, mask = self.render(aspect_ratio='16:9 (Widescreen)', width=1536, height=576, multiple=16)
        self.assertEqual(tuple(image.shape), (1, 864, 1536, 3))
        self.assertEqual(float(mask.min()), 1.0)             # 全图都要生成

    def test_resample_algorithms_produce_the_same_box(self):
        # 缩放算法只影响像素，不影响摆放：五种算法出来的画布尺寸 / 遮罩必须一致
        self.assertIn("nearest-exact", BOARD.RESAMPLE_OPTIONS)
        src = torch.rand((1, 900, 1600, 3))
        boxes = []
        for algo in BOARD.RESAMPLE_OPTIONS:
            image, mask = self.render(aspect_ratio='16:9 (Widescreen)', width=1024, height=576,
                                      multiple=16, resample=algo, image=src)
            self.assertEqual(tuple(image.shape), (1, 576, 1024, 3), algo)
            boxes.append(mask)
        for other in boxes[1:]:
            self.assertTrue(torch.equal(boxes[0], other))

    def test_no_resample_when_size_matches(self):
        # 尺寸刚好一致时必须逐位复制原图（任何算法都不该介入）
        src = torch.rand((1, 576, 576, 3))
        for algo in BOARD.RESAMPLE_OPTIONS:
            image, _ = self.render(aspect_ratio='16:9 (Widescreen)', width=1024, height=576,
                                   multiple=16, resample=algo, image=src)
            self.assertTrue(torch.equal(image[0, 0:576, 224:800, :], src[0]), algo)

    def test_feathering_defaults_to_off(self):
        # 默认 0 = 关闭羽化：图片区的遮罩必须是干净的 0（原图 100% 不变）
        _, mask = self.render(aspect_ratio='1:1 (Square)', width=1024, height=1024,
                              multiple=16, image=self.image)
        self.assertEqual(float(mask[0, 256:768, 256:768].max()), 0.0)

    def test_feathering_softens_the_seam_inside_the_image(self):
        # 512² 图放在 1024² 画布正中，羽化 32：图片边缘内侧按 ((32-d)/32)² 从 1 渐变到 0
        _, mask = self.render(aspect_ratio='1:1 (Square)', width=1024, height=1024,
                              multiple=16, feathering=32, image=self.image)
        self.assertAlmostEqual(float(mask[0, 256, 256]), 1.0, places=5)          # d=0
        self.assertAlmostEqual(float(mask[0, 256 + 16, 300]), 0.25, places=5)    # d=16
        self.assertEqual(float(mask[0, 256 + 32, 300]), 0.0)                     # d=32 → 0
        self.assertEqual(float(mask[0, 0, 0]), 1.0)                              # 外补区不受影响
        self.assertEqual(float(mask[0, 512, 512]), 0.0)                          # 图片中心不动


class MergeTests(unittest.TestCase):
    """外补融合：不管模型把画布画成什么，图片区都要回到原图。"""

    def setUp(self):
        self.board = BOARD.XB_OutpaintBoard()
        self.merge = BOARD.XB_OutpaintMerge()
        self.orig = torch.zeros((1, 512, 512, 3))
        self.orig[..., 0] = 1.0                                    # 纯红原图
        self.canvas, self.mask, self.seam = self.board.render(
            aspect_ratio='1:1 (Square)', width=1024, height=1024, multiple=16,
            feathering=32, image=self.orig)["result"]
        self.fake = torch.zeros_like(self.canvas)
        self.fake[..., 1] = 1.0                                    # 模型把整张画布画成绿色

    def test_seam_payload_carries_what_is_needed(self):
        self.assertEqual(self.seam["canvas"], (1024, 1024))
        self.assertEqual(self.seam["rect"], (256, 256, 512, 512))
        self.assertEqual(self.seam["source"], (512, 512))
        self.assertEqual(self.seam["feather"], 32)
        self.assertTrue(torch.equal(self.seam["original"], self.orig))

    def test_original_pixels_are_restored_bit_exact(self):
        out, mask = self.merge.merge(self.fake, self.seam, sync_feather=False,
                                     feather=0, color_match=0.0)
        # 硬边模式：图片矩形内逐位等于原图（模型怎么画都不影响）
        self.assertTrue(torch.equal(out[0, 256:768, 256:768, :], self.orig[0]))
        self.assertEqual(float(mask[0, 512, 512]), 0.0)             # 遮罩 = 0

    def test_padding_keeps_the_generated_content(self):
        out, mask = self.merge.merge(self.fake, self.seam, sync_feather=False,
                                     feather=0, color_match=0.0)
        self.assertEqual(float(out[0, 0, 0, 1]), 1.0)               # 左上角外补区 = 生成内容
        self.assertEqual(float(mask[0, 0, 0]), 1.0)

    def test_feather_blends_and_mask_matches_the_band(self):
        out, mask = self.merge.merge(self.fake, self.seam, sync_feather=False,
                                     feather=32, color_match=0.0)
        # 图片边内 16px：带 = ((32-16)/32)² = 0.25 → 0.75 生成 + 0.25 原图
        self.assertAlmostEqual(float(out[0, 272, 300, 0]), 0.75, places=5)
        self.assertAlmostEqual(float(out[0, 272, 300, 1]), 0.25, places=5)
        self.assertAlmostEqual(float(mask[0, 272, 300]), 0.25, places=5)

    def test_sync_feather_follows_the_board_value(self):
        a, ma = self.merge.merge(self.fake, self.seam, sync_feather=True, color_match=0.0)
        b, mb = self.merge.merge(self.fake, self.seam, sync_feather=False,
                                 feather=32, color_match=0.0)
        self.assertTrue(torch.equal(a, b))
        self.assertTrue(torch.equal(ma, mb))

    def test_color_match_reduces_the_cast(self):
        # 模型把原图区整体提亮 0.05 → 贴回时按"没被改动的像素"估偏移，把接缝带拉回原色
        board = BOARD.XB_OutpaintBoard()
        orig = torch.full((1, 512, 512, 3), 0.5)
        _, _, seam = board.render(aspect_ratio='1:1 (Square)', width=1024, height=1024,
                                  multiple=16, feathering=64, image=orig)["result"]
        gen = torch.full((1, 1024, 1024, 3), 0.5)
        gen[0, 256:768, 256:768, :] = orig[0] + 0.05
        off, _ = self.merge.merge(gen, seam, sync_feather=False, feather=64, color_match=0.0)
        on, _ = self.merge.merge(gen, seam, sync_feather=False, feather=64, color_match=1.0)
        # 过渡带 d=32 / 羽化 64 → 带 = 0.25
        self.assertAlmostEqual(float(off[0, 288, 300, 0]), 0.25 * 0.55 + 0.75 * 0.5, places=4)
        self.assertAlmostEqual(float(on[0, 288, 300, 0]), 0.5, places=3)

    def test_without_original_it_passes_the_generated_image_through(self):
        _, _, seam = self.board.render(aspect_ratio='1:1 (Square)', width=512,
                                       height=512, multiple=16)["result"]
        gen = torch.rand((1, 512, 512, 3))
        out, mask = self.merge.merge(gen, seam)
        self.assertTrue(torch.equal(out, gen))
        self.assertEqual(float(mask.max()), 0.0)

    def test_generated_size_mismatch_is_resampled_to_the_canvas(self):
        half = torch.zeros((1, 512, 512, 3))
        out, mask = self.merge.merge(half, self.seam, sync_feather=False, feather=0)
        self.assertEqual(tuple(out.shape), (1, 1024, 1024, 3))
        self.assertEqual(tuple(mask.shape), (1, 1024, 1024))


if __name__ == '__main__':
    unittest.main()
