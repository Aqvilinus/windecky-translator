# providers/nllb_downloader.py
# The offline translation model (NLLB-200 1.3B, CTranslate2 int8), downloaded from Hugging Face

import logging
import os

from .model_download import DownloadError, ModelDownload

logger = logging.getLogger(__name__)

# Map plugin language codes to NLLB-200 language codes
NLLB_LANG_MAP = {
    "en": "eng_Latn",
    "ja": "jpn_Jpan",
    "zh-CN": "zho_Hans",
    "zh-TW": "zho_Hant",
    "ko": "kor_Hang",
    "de": "deu_Latn",
    "fr": "fra_Latn",
    "es": "spa_Latn",
    "it": "ita_Latn",
    "pt": "por_Latn",
    "ru": "rus_Cyrl",
    "ar": "arb_Arab",
    "nl": "nld_Latn",
    "no": "nob_Latn",  # Norwegian Bokmål
    "pl": "pol_Latn",
    "tr": "tur_Latn",
    "uk": "ukr_Cyrl",
    "el": "ell_Grek",
    "fi": "fin_Latn",
    "th": "tha_Thai",
    "vi": "vie_Latn",
    "ro": "ron_Latn",
    "bg": "bul_Cyrl",
    "hi": "hin_Deva",
    "id": "ind_Latn",
    "hr": "hrv_Latn",
    "cs": "ces_Latn",
    "hu": "hun_Latn",
    "sv": "swe_Latn",
    "da": "dan_Latn",
}

REQUIRED_MODEL_FILES = ["model.bin", "sentencepiece.bpe.model", "config.json", "shared_vocabulary.txt"]
OPTIONAL_MODEL_FILES = ["tokenizer_config.json", "special_tokens_map.json"]

HF_REPO = "JustFrederik/nllb-200-distilled-1.3B-ct2-int8"
# A fixed commit (not "main") and each file's sha256: a changed upstream file is refused instead of installed
HF_COMMIT = "30c36268408177b0fce2bfcfa205d877accd327d"
HF_BASE_URL = f"https://huggingface.co/{HF_REPO}/resolve/{HF_COMMIT}/{{filename}}"
FILE_SHA256 = {
    "model.bin": "72d7533dc7a0e8f10f19a650d4e90faf9cbfa899db5411ad124bd5802bd91263",
    "sentencepiece.bpe.model": "14bb8dfb35c0ffdea7bc01e56cea38b9e3d5efcdcb9c251d6b40538e1aab555a",
    "config.json": "0c2f6fa2057c7264d052fb4a62ba3476eeae70487acddfa8e779a53a00cbf44c",
    "shared_vocabulary.txt": "a132a83330f45514c2476eb81d1d69b3c41762264d16ce0a7ea982e5d6c728e5",
    "tokenizer_config.json": "d1aa8c3697d3e35674f97b5b7e9c99d22b010f528e80140257d97316be90d044",
    "special_tokens_map.json": "992bd4ed610d644d6823081937bcc91bb8878dd556cea4ae5327f2480361330e",
}


class NLLBDownload(ModelDownload):
    name = "nllb-200-distilled-1.3B"
    approx_size_mb = 1410
    required_files = tuple(REQUIRED_MODEL_FILES)

    def _install(self, staging_dir: str) -> None:
        for filename in REQUIRED_MODEL_FILES + OPTIONAL_MODEL_FILES:
            self._check_cancel()
            # model.bin is nearly all of the download: the bar follows it
            progress = self._set_progress if filename == "model.bin" else None
            try:
                digest = self._fetch(HF_BASE_URL.format(filename=filename), os.path.join(staging_dir, filename),
                                     progress=progress, timeout=30)
            except DownloadError as e:
                if filename in OPTIONAL_MODEL_FILES and "HTTP 404" in str(e):
                    continue  # an optional file the repo doesn't have
                raise
            if digest != FILE_SHA256[filename]:
                raise DownloadError(f"{filename} is damaged or changed upstream (hash mismatch)")
