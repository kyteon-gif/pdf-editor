"""
tests/test_unit3_model_registry.py
Unit 3：驗證 ModelRegistry 的本機檢查、status 格式、path 回傳。

執行：
    pytest tests/test_unit3_model_registry.py -v

注意：不會實際觸發網路下載。若模型已放在 models/ 下，
      is_ready() 應回傳 True；尚未放置則回傳 False 但不報錯。
"""


from app.services.model_registry import ModelRegistry
from config import MODEL_MANIFEST


class TestModelRegistry:

    def setup_method(self):
        """每個測試前重新 ensure_all，確保 _registry 已填充。"""
        ModelRegistry.ensure_all()

    def test_status_returns_all_models(self):
        """status() 應包含 MODEL_MANIFEST 中的所有模型名稱。"""
        s = ModelRegistry.status()
        for name in MODEL_MANIFEST:
            assert name in s, f"status() 缺少 {name}"

    def test_status_schema(self):
        """每個模型條目有必要欄位且型別正確。"""
        s = ModelRegistry.status()
        for name, info in s.items():
            assert isinstance(info["ready"],    bool),  f"{name}.ready 型別錯誤"
            assert isinstance(info["required"], bool),  f"{name}.required 型別錯誤"
            assert isinstance(info["size_gb"],  float), f"{name}.size_gb 型別錯誤"
            assert isinstance(info["license"],  str),   f"{name}.license 型別錯誤"

    def test_path_returns_str_or_none(self):
        """path() 只能回傳 str 或 None，不能是其他型別。"""
        for name in MODEL_MANIFEST:
            p = ModelRegistry.path(name)
            assert p is None or isinstance(p, str), f"{name}.path 型別錯誤: {type(p)}"

    def test_is_ready_consistent_with_path(self):
        """is_ready() 與 path() 結果一致：有 path 就 ready，無 path 就 not ready。"""
        for name in MODEL_MANIFEST:
            ready = ModelRegistry.is_ready(name)
            path  = ModelRegistry.path(name)
            if ready:
                assert path is not None, f"{name} is_ready=True 但 path=None"
            else:
                assert path is None, f"{name} is_ready=False 但 path={path}"

    def test_ready_model_path_exists(self):
        """若 is_ready，path 對應的目錄應該確實存在。"""
        from pathlib import Path
        for name in MODEL_MANIFEST:
            if ModelRegistry.is_ready(name):
                p = Path(ModelRegistry.path(name))
                assert p.exists(), f"{name} path {p} 不存在"

    def test_required_model_logged_if_missing(self):
        """
        測試不會讓必要模型缺少時拋出 Exception（只警告）。
        此測試確認 ensure_all() 在任何情況下都不 raise。
        """
        try:
            ModelRegistry.ensure_all()
        except Exception as e:
            assert False, f"ensure_all() 不應拋出例外，但收到: {e}"
