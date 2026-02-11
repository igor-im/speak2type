"""Tests for model manager modules."""

from pathlib import Path

from speak2type.model_managers import ModelSpec, PINNED_MODELS, ParakeetModelManager


def test_parakeet_model_manager_import_and_init(tmp_path: Path) -> None:
    """Parakeet model manager should be importable and constructible."""
    manager = ParakeetModelManager(
        model_dir=tmp_path / "models",
        cache_dir=tmp_path / "cache",
    )
    assert manager.model_dir.exists()
    assert manager.cache_dir.exists()


def test_parakeet_model_specs_are_typed(tmp_path: Path) -> None:
    """Pinned model specifications should deserialize to ModelSpec objects."""
    manager = ParakeetModelManager(
        model_dir=tmp_path / "models",
        cache_dir=tmp_path / "cache",
    )
    models = manager.list_available_models()
    assert models
    assert all(isinstance(model, ModelSpec) for model in models)


def test_default_model_selection_returns_known_id(tmp_path: Path) -> None:
    """Locale-based default model selection should return a pinned model id."""
    manager = ParakeetModelManager(
        model_dir=tmp_path / "models",
        cache_dir=tmp_path / "cache",
    )
    model_id = manager.get_default_model_for_locale("en_US")
    assert model_id in PINNED_MODELS
