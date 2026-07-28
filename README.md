# ctld-launcher

Hamlibの`rigctld`/`rotctld`をGUIから簡単に設定・起動できるランチャーアプリ。

リグ機種・シリアルポート・通信速度・デバッグレベルなどをプルダウンから選択し、
「OK」を押すだけで`rigctld`/`rotctld`を起動できるようにすることを目指しています。
Linux/Windows/macOSに対応予定です。

詳細は[CLAUDE.md](CLAUDE.md)を参照してください。

## 開発中

まだ開発初期段階です。

```bash
pip install -e ".[dev]"
pytest
```
