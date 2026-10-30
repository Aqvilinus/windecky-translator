#!/usr/bin/env python3
"""
Subprocess OCR runner for RapidOCR.

Runs in a separate process to avoid threading conflicts with Decky Loader's
async environment. Supports two modes:

  Oneshot (default):
      python rapidocr_subprocess.py <image_path> <models_dir> <min_confidence>
                                    [box_thresh] [unclip_ratio] [lang_family]
      ONNX is forced to 1 thread to avoid async deadlocks.

  Worker (--worker):
      python rapidocr_subprocess.py --worker
      Long-lived. Reads JSON-per-line from stdin, writes JSON-per-line to stdout.
      Engine is created once from the first "init" message and reused across
      requests. Worker rebuilds the engine when the requested lang_family
      changes, since each language family uses a different recognition model.
      ONNX uses multiple threads since this process has no asyncio event loop.
"""

import json
import os
import sys

# Maps language family -> (rec model filename, dict filename)
LANG_MODEL_MAP = {
    'ch':      ('ch_rec.onnx',      'ch_dict.txt'),
    'english': ('english_rec.onnx', 'english_dict.txt'),
    'latin':   ('latin_rec.onnx',   'latin_dict.txt'),
    'eslav':   ('eslav_rec.onnx',   'eslav_dict.txt'),
    'korean':  ('korean_rec.onnx',  'korean_dict.txt'),
    'greek':   ('greek_rec.onnx',   'greek_dict.txt'),
    'thai':    ('thai_rec.onnx',    'thai_dict.txt'),
}

# Has to happen before the heavy imports since numpy/onnx read env at load.
_WORKER_MODE = '--worker' in sys.argv

# Set threading environment BEFORE any imports
if not _WORKER_MODE:
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['MKL_NUM_THREADS'] = '1'
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    os.environ['VECLIB_MAXIMUM_THREADS'] = '1'
    os.environ['NUMEXPR_NUM_THREADS'] = '1'


def _build_engine(models_dir, min_confidence, box_thresh, unclip_ratio,
                  lang_family, intra_threads):
    # Imports inside the function so the env vars set at module top apply.
    from rapidocr import RapidOCR, EngineType

    # Detection model is always the same (PP-OCRv5 mobile)
    det_model = os.path.join(models_dir, "ch_PP-OCRv5_mobile_det.onnx")
    cls_model = os.path.join(models_dir, "ch_ppocr_mobile_v2.0_cls_infer.onnx")

    # Recognition model + dict depends on language family
    lang_family = lang_family or 'ch'
    rec_file, dict_file = LANG_MODEL_MAP.get(lang_family, ('ch_rec.onnx', 'ch_dict.txt'))
    rec_model = os.path.join(models_dir, rec_file)
    rec_keys = os.path.join(models_dir, dict_file)

    models_exist = all([
        os.path.exists(det_model),
        os.path.exists(rec_model),
        os.path.exists(cls_model),
    ])

    # Initialize RapidOCR with single-threaded ONNX
    params = {
        "Global.text_score": min_confidence,
        "Det.box_thresh": box_thresh,
        "Det.unclip_ratio": unclip_ratio,
        "Det.engine_type": EngineType.ONNXRUNTIME,
        "Cls.engine_type": EngineType.ONNXRUNTIME,
        "Rec.engine_type": EngineType.ONNXRUNTIME,
        "EngineConfig.onnxruntime.intra_op_num_threads": intra_threads,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
    }
    if models_exist:
        params["Det.model_path"] = det_model
        params["Cls.model_path"] = cls_model
        params["Rec.model_path"] = rec_model
        if os.path.exists(rec_keys):
            params["Rec.rec_keys_path"] = rec_keys

    return RapidOCR(params=params)


def _load_image_rgb(image_path):
    from PIL import Image
    import numpy as np

    # Load image
    img = Image.open(image_path)

    # Ensure RGB format
    if img.mode in ('RGBA', 'P'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'RGBA':
            background.paste(img, mask=img.split()[3])
        else:
            background.paste(img)
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    # Convert to numpy array
    return np.array(img)


def _result_to_regions(result, min_confidence):
    # Parse results -- rapidocr 3.x returns a dataclass with .boxes, .txts, .scores
    regions = []
    if result and result.txts:
        for box, text, confidence in zip(result.boxes, result.txts, result.scores):
            if not text or not text.strip():
                continue
            if confidence < min_confidence:
                continue

            # Convert polygon to rectangle (box is np.ndarray shape (4, 2))
            if box is not None and len(box) >= 4:
                xs = [pt[0] for pt in box]
                ys = [pt[1] for pt in box]
                rect = {
                    "left": int(min(xs)),
                    "top": int(min(ys)),
                    "right": int(max(xs)),
                    "bottom": int(max(ys)),
                }
            else:
                rect = {"left": 0, "top": 0, "right": 0, "bottom": 0}

            is_dialog = len(text) > 15 or any(p in text for p in '.?!,:;"')
            regions.append({
                "text": text.strip(),
                "rect": rect,
                "confidence": float(confidence),
                "is_dialog": is_dialog,
            })
    return regions


def run_ocr(image_path, models_dir, min_confidence, box_thresh=0.5,
            unclip_ratio=1.6, lang_family='ch'):
    """Run OCR on the image and return results as JSON."""
    debug_info = []
    try:
        debug_info.append(f"Python: {sys.version}")
        import numpy as np
        debug_info.append(f"NumPy version: {np.__version__}")
    except ImportError as e:
        return {"error": f"Import failed: {e}", "regions": [], "debug": debug_info}

    try:
        debug_info.append(
            f"Settings: text_score={min_confidence}, box_thresh={box_thresh}, "
            f"unclip_ratio={unclip_ratio}, lang_family={lang_family}"
        )
        engine = _build_engine(
            models_dir, min_confidence, box_thresh, unclip_ratio,
            lang_family, intra_threads=1,
        )

        img_np = _load_image_rgb(image_path)
        debug_info.append(f"Image shape: {img_np.shape}, dtype: {img_np.dtype}")

        # Run OCR
        result = engine(img_np)
        regions = _result_to_regions(result, min_confidence)
        return {"error": None, "regions": regions, "debug": debug_info}

    except Exception as e:
        import traceback
        debug_info.append(f"Exception: {traceback.format_exc()}")
        return {"error": str(e), "regions": [], "debug": debug_info}


def _write_line(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def worker_main():
    """
    Long-lived worker. Protocol:

      >>> {"type":"init","models_dir":...,"min_confidence":0.5,"box_thresh":0.5,
           "unclip_ratio":1.6,"lang_family":"ch","threads":4}
      <<< {"type":"ready","error":null}

      >>> {"type":"recognize","image_path":"/tmp/x.png","lang_family":"ch"}
      <<< {"type":"result","error":null,"regions":[...]}

      >>> {"type":"shutdown"}  (or stdin closes)
      (worker exits)
    """
    engine = None
    cfg = {
        "models_dir": "",
        "min_confidence": 0.5,
        "box_thresh": 0.5,
        "unclip_ratio": 1.6,
        "lang_family": "ch",
        "threads": 4,
    }

    def build():
        return _build_engine(
            cfg["models_dir"], cfg["min_confidence"], cfg["box_thresh"],
            cfg["unclip_ratio"], cfg["lang_family"], cfg["threads"],
        )

    try:
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                _write_line({"type": "result", "error": f"bad json: {e}", "regions": []})
                continue

            mtype = msg.get("type")

            if mtype == "init":
                try:
                    for k in cfg.keys():
                        if k in msg:
                            cfg[k] = msg[k]
                    engine = build()
                    _write_line({"type": "ready", "error": None})
                except Exception as e:
                    import traceback
                    _write_line({"type": "ready", "error": f"{e}\n{traceback.format_exc()}"})

            elif mtype == "recognize":
                try:
                    if engine is None:
                        _write_line({"type": "result", "error": "not initialized", "regions": []})
                        continue

                    req_lang = msg.get("lang_family") or cfg["lang_family"]
                    if req_lang != cfg["lang_family"]:
                        cfg["lang_family"] = req_lang
                        engine = build()

                    image_path = msg.get("image_path", "")
                    if not image_path or not os.path.exists(image_path):
                        _write_line({"type": "result", "error": "image not found", "regions": []})
                        continue

                    img_np = _load_image_rgb(image_path)
                    result = engine(img_np)
                    regions = _result_to_regions(result, cfg["min_confidence"])
                    _write_line({"type": "result", "error": None, "regions": regions})
                except Exception as e:
                    import traceback
                    _write_line({
                        "type": "result",
                        "error": f"{e}",
                        "regions": [],
                        "trace": traceback.format_exc(),
                    })

            elif mtype == "shutdown":
                break

            else:
                _write_line({"type": "result", "error": f"unknown type: {mtype}", "regions": []})

    except KeyboardInterrupt:
        pass


def main():
    if _WORKER_MODE:
        worker_main()
        return

    if len(sys.argv) < 4:
        print(json.dumps({
            "error": "Usage: rapidocr_subprocess.py <image_path> <models_dir> "
                     "<min_confidence> [box_thresh] [unclip_ratio] [lang_family]",
            "regions": [],
        }))
        sys.exit(1)

    image_path = sys.argv[1]
    models_dir = sys.argv[2]
    min_confidence = float(sys.argv[3])
    box_thresh = float(sys.argv[4]) if len(sys.argv) > 4 else 0.5
    unclip_ratio = float(sys.argv[5]) if len(sys.argv) > 5 else 1.6
    lang_family = sys.argv[6] if len(sys.argv) > 6 else 'ch'

    result = run_ocr(image_path, models_dir, min_confidence, box_thresh,
                     unclip_ratio, lang_family)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
