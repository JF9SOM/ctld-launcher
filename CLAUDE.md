# ctld-launcher

Hamlibの`rigctld`(リグ制御デーモン)/`rotctld`(ローテーター制御デーモン)をGUIから簡単に設定・起動できるランチャーアプリ。

## 背景・目的

`rigctld`/`rotctld`はTCP経由で複数のソフトからシリアルポートを共有できるが、リグ機種番号・シリアル速度・ポート・デバッグレベルなどをコマンドライン引数で細かく指定する必要があり、PCに詳しくないユーザーには敷居が高い。本アプリはこれらをプルダウンメニューで選択させ、GUI上の「OK」操作だけで`rigctld`/`rotctld`を自動起動できるようにする。

対象OS: Linux, Windows, macOS(3プラットフォーム対応)

## アーキテクチャ方針(確定事項)

- **実装スタック**: Python + PySide6
  - 姉妹プロジェクト[FBSAT59](../FBSAT59)がPyInstaller + AppImage(Linux)/NSIS(Windows)/dmg(macOS)のパッケージングパイプライン、hamlibビルドCI、i18n(`locale/`)、`platformdirs`によるユーザー設定ディレクトリ管理などの実績を持つため、それらのパターンを踏襲する。
- **hamlibのバンドル方法**: 本リポジトリ専用のCI(GitHub Actions)でhamlib 4.7.1をソースからビルドし、以下を独自にバンドルする。FBSAT59の`hamlib-bundle`リリースには依存しない(疎結合)。
  - `rigctld` / `rotctld` / `rigctl` / `rotctl` 実行ファイル(GUIから起動する本体)
  - SWIG生成のPythonバインディング(`Hamlib.py` / `_Hamlib.so`等) — 将来的な直接制御用に同梱。ただしモデル一覧の動的取得には**使っていない**(理由はステップ5参照: `Hamlib.Rig(model_id)`が特定モデルで回復不能なクラッシュを起こすことが判明したため、`rigctld --list`のサブプロセス実行+パースに切り替えた)
  - 参考: FBSAT59の`.github/workflows/ci.yml`「Build Hamlib 4.7.1 from source」ステップが土台になる(`./configure && make && make install`で既に`rigctld`/`rotctld`はビルドされているが、現状バンドルパッケージにコピーされていないだけ)
- **自動起動・サービス化の範囲(v1)**: ログイン時自動起動のみに限定し、管理者/root権限が必要なシステム全体サービス化は将来のバックログとする。
  - Linux: `~/.config/systemd/user/`にunit生成 → `systemctl --user enable --now`
  - macOS: `~/Library/LaunchAgents/`にplist生成 → `launchctl load`
  - Windows: スタートアップフォルダ登録 or レジストリRunキー

## 主要機能(予定)

- リグ用/ローテーター用タブ、複数プロファイル管理(Rig1/Rig2など)
- モデル選択(メーカー→モデルの検索可能コンボボックス、hamlibバインディングから動的取得)
- シリアルポート自動検出(`pyserial`の`serial.tools.list_ports`)+ 手動入力
- 通信速度・データビット・パリティ・ストップビット・フロー制御(詳細設定は折りたたみ表示)
- 待受アドレス/ポート番号、デバッグレベル(`-v`〜`-vvvvv`相当)、ログ出力先
- 上級者向け自由記述オプション欄(civaddr等rigctld/rotctld固有フラグ用)
- OK押下でサブプロセスとして起動、GUI内ログビュー、Start/Stop/Restart、システムトレイ常駐
- プロファイルはJSON等で保存(`platformdirs`使用)

## 開発ステップ

1. ✅ プロジェクト雛形(`pyproject.toml`、ディレクトリ構成) — `src/ctld_launcher/`配下に`core/`・`ui/`パッケージを用意。`main.py`はプレースホルダーのQMainWindow。`pip install -e ".[dev]"` / `ruff` / `mypy` / `pytest`が通ることを確認済み。
2. ✅ hamlibビルドCI(`.github/workflows/build-hamlib.yml`) — FBSAT59のci.ymlを土台に、`rigctld`/`rotctld`/`rigctl`/`rotctl`をバンドルに追加。ポータブル版のみ生成(PyInstaller用固定パスビルドは不要なので省略)。`hamlib-bundle`プレリリースにアップロードする独立ワークフロー(手動起動 + ワークフローファイル変更時のpushで動作確認可能)。
3. ✅ コア: サブプロセス管理・プロファイル保存 — `core/profile.py`(`Profile`データクラス+JSON永続化)、`core/process_manager.py`(`build_command()`でrigctld/rotctld引数構築、`CtldProcess`で起動/停止/再起動+出力ログ捕捉)。実機(バンドル版rigctld、Dummyリグ)でTCP疎通確認済み。副産物としてhamlib-bundle CIのRUNPATH破損バグ2件を発見・修正(`patchelf`での後付けRUNPATH書き込み方式に変更)。
4. ✅ GUI: モデル/ポート選択画面 — `ui/main_window.py`(プロファイルサイドバー+モデル/接続/ネットワーク/デバッグ/追加オプションフォーム+実行中コマンドプレビュー+起動/停止/再起動+ログビューア)、`ui/tray.py`(システムトレイアイコン、稼働状況バッジ、プロファイルごとのワンクリック起動/停止、「設定を開く」「終了」)。ウィンドウを閉じても終了せず非表示になるだけ(トレイ常駐)。実機(バンドル版rigctld)でスクリーンショット確認済み。
   - hamlib実行ファイルの解決(`core/hamlib_locator.py`)は現状PATH検索のみ。バンドル自動ダウンロード(FBSAT59のHamlib Update相当)は今後の課題。
5. ✅ モデル一覧の動的取得 — `core/hamlib_models.py`。`rigctld`/`rotctld`の`--list`出力(固定幅テーブル、見出し行から列位置を動的検出してパース)をサブプロセスとして実行・解析し、メーカー別にグルーピング。
   - **Hamlib Pythonバインディングの`Rig()`/`Rot()`クラスは意図的に不採用**: システムのPython 3.12用に自前ビルドした`_Hamlib.so`で全`RIG_MODEL_*`定数を`Hamlib.Rig(model_id)`に通して実機検証したところ、`RIG_MODEL_ARMSTRONG`(id=3)でlibhamlib内部から回復不能な`Hash collision!!! Fatal error!!`が発生しPythonの例外処理では捕捉できずプロセスごと落ちることを確認。`--list`は`rig_list_foreach()`内部実装を使うため同じ経路を通らず安全。サブプロセス分離により、将来別のクラッシュが見つかってもGUI本体は道連れにならない。
   - 実機(Linux版hamlib-bundle)で75メーカー・Icom 84機種の取得を確認済み。
6. OS別自動起動(ログイン時)
7. パッケージング(AppImage/NSIS/dmg)

## 既知の未実装事項

- CI: hamlibバンドル以外(lint/mypy/pytest)を回す通常のテストCI(`ci.yml`)がまだ存在しない。これまでのテストはすべてローカル実行で確認している。
- hamlib実行ファイルの自動ダウンロード(バンドルリリースからの取得・展開)は未実装。現状PATH検索のみ。

## 関連プロジェクト

- [FBSAT59](../FBSAT59) — 姉妹プロジェクト。`rigctld`/`rotctld`の**クライアント**側(接続して制御する側)。hamlibビルドCI・パッケージングスクリプトの参考元。本プロジェクトはその**サーバー起動側**を担う。
