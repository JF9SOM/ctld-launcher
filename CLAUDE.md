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
- **自動起動・サービス化の範囲(v1)**: ログイン時自動起動のみに限定し、管理者/root権限が必要なシステム全体サービス化は将来のバックログとする。実装は`core/autostart.py`(ステップ6参照)。
  - Linux: `~/.config/systemd/user/`にunit生成 → `systemctl --user enable`(`--now`は付けない — チェックボックスON時にアプリが二重起動しないよう、反映は次回ログイン時)
  - macOS: `~/Library/LaunchAgents/`にplist生成(`launchctl load`は同じ理由で呼ばない — launchdが次回ログイン時に自動で拾う)
  - Windows: `HKEY_CURRENT_USER\...\Run`レジストリキー(`winreg`、追加依存なし、管理者権限不要)
  - `autostart.default_command()`は起動コマンドの末尾に`--minimized`フラグ(`MINIMIZED_FLAG`)を付与する。`main.py`の`should_show_on_startup()`がこれを見て、手動起動(ダブルクリック・アプリメニュー等、このフラグが付かない)では設定画面を即座に開き、自動起動経由の起動ではトレイに常駐したまま画面を開かない。これがないと、ログイン時自動起動でない手動起動でも画面が開かず、ユーザーが「起動できていない」と誤解する問題があった。

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
6. ✅ OS別自動起動(ログイン時) — `core/autostart.py`(Linux/macOS/Windows対応、詳細は上記アーキテクチャ方針参照)。`Profile.auto_start`でプロファイル単位の「アプリ起動時に自動起動するか」を管理(OSレベルのアプリ自動起動とは別軸)。GUI: サイドバーに「ログイン時に自動起動」チェックボックス(実OS状態を反映・トグルで即座に有効/無効化)、フォームヘッダーに「自動起動」チェックボックス(プロファイル単位)。`main.py`起動時に`auto_start=True`のプロファイルを自動起動。Linuxは実際の`systemctl --user`で有効化→確認→無効化のフルサイクルを検証済み。macOSはplist生成ロジックを検証(このマシンに`launchctl`がないため生成内容の妥当性のみ)、Windowsは`winreg`をモックして検証(このマシンに`winreg`自体がないため)。
7. ✅ パッケージング(AppImage/NSIS/dmg) — `scripts/ctld-launcher.spec`(PyInstaller、hamlib-bundleを`datas`として同梱。`binaries`ではなく`datas`を使うのは、PyInstallerの`binaries`は依存関係解析・rpath書き換えを行い、build-hamlib.yml CIで検証済みの`$ORIGIN`/`@loader_path`相対レイアウトと衝突するため)。`scripts/build-appimage.sh`/`installer.nsi`/`build-dmg.sh`はFBSAT59の実績あるスクリプトを土台に簡略化。`core/hamlib_locator.py`は`sys._MEIPASS`(PyInstallerの公式なバンドルデータ検出方法)経由でバンドル済みhamlibを優先的に検出。
   - アイコンは`assets/generate_icons.py`(Pillow)で生成したプレースホルダー(トレイアイコンと同じ紫のマーク)。PNG/icoはコミット済み、icnsはこのマシンに`sips`/`iconutil`がない(macOS専用ツール)ためmacOS CI側で`scripts/generate-icns.sh`により都度生成。
   - `.github/workflows/build-release.yml` — `v*`タグpushで3プラットフォーム一括ビルド・リリース添付。`workflow_dispatch`で個別プラットフォームのテストビルドも可能。
   - **Linuxはこのマシンで実機検証済み**: PyInstallerビルド→バンドル済みrigctldが`_MEIPASS/hamlib/`から検出される→自動起動プロファイルで実際にrigctldが起動しTCP応答(`145000000`)を確認、を`dist/ctld-launcher/`のPyInstaller出力とAppImage本体の両方で確認。既存の`rigctld-ftx1`等システムサービスへの影響なし。
   - 3プラットフォームとも`workflow_dispatch`でのCI実行に成功済み(Linux/Windows/macOS)。

## 多言語対応(i18n)

- `src/ctld_launcher/i18n.py` — Python標準`gettext`ベース。FBSAT59の`src/i18n/__init__.py`と同じ設計方針(**ソースコードは英語で書き、`.po`ファイルで日本語等へ翻訳する**)。
- `locale/ja/LC_MESSAGES/ctld_launcher.po`/`.mo` — 日本語訳(既存のUI文言と完全一致するよう作成)。`locale/ctld_launcher.pot`が翻訳テンプレート(`pygettext3`で抽出)。
- 起動時に`main.py`が`detect_system_language()`で自動判定。サイドバー上部に手動切り替えコンボ(English/日本語)もあり、再起動不要でその場に全UI文言を再翻訳する(`MainWindow._retranslate_ui()`)。
  - **macOS特有の注意**: `QLocale.system().name()`だけに頼ると、実際の使用言語が日本語のMacでも英語判定になる不具合が実機で確認された(Apple公証を行っていないビルドではLaunch Servicesにアプリのロケール情報が正しく登録されないためと推測)。そのため`detect_system_language()`はmacOS(`sys.platform == "darwin"`)の場合のみ、まず`defaults read -g AppleLanguages`(macOS標準のユーザー言語設定を直接読む、署名状況に左右されないコマンド)で判定し、取得できなければ`QLocale`にフォールバックする。
- **重要な設計上の注意**: `ui/main_window.py`の`DEBUG_LEVELS`等の選択肢リストは、あえてモジュール直下の定数ではなく`_debug_levels()`等の関数にしている。`_()`はモジュールインポート時ではなく毎回呼び出し時に現在の翻訳を参照するが、モジュールレベルの定数として一度だけ評価してしまうと、`main()`内で`set_language()`を呼ぶより前(モジュールimport時点)に固定されてしまうため。
- PyInstallerで`locale/`ディレクトリをバンドル(`assets/`と同様)。実機(Linux)でバンドル済み`.mo`が正しく`_MEIPASS/locale/`から読み込まれ、日本語・英語両方で正しく表示されることを確認済み。

## USB自動起動/停止(ホットプラグ検知)

- `core/usb_watch.py` — Linuxのudev+systemd(`ACTION=="add"`でサービス起動、`"remove"`で停止)と同等の体験を、macOS/Windowsを含む3プラットフォーム共通のコードで実現するための実装。
  - **udev相当をmacOS/Windowsに個別移植する方針は不採用**: macOSのIOKit、WindowsのWM_DEVICECHANGE/WMIはudevとは全く別のAPIで、しかもOS起動時から独立して動かす(=アプリ未起動でも反応する)にはヘルパープロセス/デーモンの追加実装とパッケージングが必要になり、3通りのOS別実装を保守するコストに見合わない。ユーザー(JF9SOM)自身「アプリが起動していないときまで自動起動するようにしたいわけではない」と明言したため、**ctld-launcher自体が起動している間だけ動く軽量なポーリング方式**を採用。
  - `pyserial`の`list_ports.comports()`を(プロファイルごとにUSBホットプラグが有効なものが1つ以上あるときだけ)2秒間隔でポーリングし、前回ポーリング時との差分からデバイスの着脱を検出する(`UsbHotplugTracker.poll()`)。
  - デバイスの識別は**ポートパスではなくVID:PID(+可能ならシリアル番号)** で行う。`/dev/ttyUSB0`やmacOSの`/dev/tty.usbserial-*`、WindowsのCOM番号はいずれも抜き差しのたびに変わりうるため、パス一致では同一デバイスの再認識に失敗する。
  - `Profile.usb_hotplug`/`usb_vid`/`usb_pid`/`usb_serial_number`で永続化。GUI側では接続グループ内の「USB接続時にこのプロファイルを自動起動・切断時に自動停止」チェックボックスをオンにした時点で、その時ポート欄に選択されているポートのVID:PID(pyserial経由)を自動的に記憶する(ユーザーがVID:PIDを手入力する必要はない)。デバイスが接続されていない状態でオンにした場合は「(USBデバイス未識別)」ステータスを表示し、実害がないことを明示する(何もトラッキングされない=無害な状態のまま)。
  - デバイス接続を検知すると、その時点の実際のポートパスで`profile.port`を更新してから起動する(ポート名が前回と変わっていても正しく追従する)。
  - 既存の`Profile.auto_start`(アプリ起動時に自動起動、プロファイル一覧の各行右端のトグルスイッチで設定)とは独立した設計。両方オンにしても害はない(`_start_profile()`/`_stop_profile()`はどちらも「既に希望の状態ならno-op」なので二重起動しない)。
  - **文言の混乱を避けるための整理**(実機テスト中のユーザーフィードバックで発覚): 当初「自動起動」という単語をサイドバー(ログイン時)・フォーム(アプリ起動時)・接続欄(USB接続時)の3箇所で使い回していたところ、どれが何を指すか分からず混乱を招いた。整理後は次の通り、単語の重複を避けている。
    - サイドバー左下「スタートアップ時に起動」(旧「ログイン時に自動起動」。あえて「自動」を付けない): アプリ自体をPCログイン時にトレイへ起動。
    - プロファイル一覧の各行右端の`ToggleSwitch`(`ui/main_window.py`のカスタムウィジェット、`_sidebar_autostart_toggles`): アプリ起動時にそのプロファイルも起動。当初はフォーム上部に「自動起動」という名前付きQCheckBoxとして存在していたが、(1) 1プロファイルずつフォームを開かないと状態を確認できない、(2) 「自動起動」という単語がサイドバー①と衝突する、という2つの理由で一覧行に移動した。さらに実機テストで「四角いチェックボックスだと、すぐ下の「削除」ボタンと並んで見えて、削除対象を選ぶチェックボックスと誤解しやすい」という指摘を受け、QCheckBoxではなくON(緑)/OFF(赤)を文字で明示する自前描画のスライドトグル(`ToggleSwitch`、`QPropertyAnimation`でノブをアニメーション)に変更した。
    - フォーム接続欄「USB接続時にこのプロファイルを自動起動・切断時に自動停止」: 主語(このプロファイルを)と起動・停止の両方を明記し、「(ソフト自体が)USB接続で自動起動する」という誤読を防いでいる。

## CI

- `.github/workflows/ci.yml` — push/PR(mainブランチ)ごとにruff(lint+format check)/mypy/pytestを実行。Hamlibのインストールは不要(テストは`_fake_ctld.py`/`_fake_hamlib_list.py`等のフェイクスクリプトで完結し、実バインディングに依存しない)。
- `.github/workflows/build-hamlib.yml` — hamlib-bundleの生成(手動起動)。
- `.github/workflows/build-release.yml` — アプリ本体のパッケージング・リリース(`v*`タグpush、または`workflow_dispatch`)。

## 既知の未実装事項

- hamlib実行ファイルの自動ダウンロード(バンドルリリースからの取得・展開)は未実装。現状PATH検索のみ。

## 修正済みの不具合(参考)

- **機種名プルダウンが`model_id`とずれて表示される**(実機テストで発覚): `MainWindow._populate_model_combo()`が、メーカーの機種一覧を並べ直すだけで「保存されている`model_id`に一致する項目を選び直す」処理を欠いていたため、フォーム再描画(プロファイル選択し直し・言語切替・USBホットプラグでの再接続時など)のたびにQtの標準動作でリストの先頭の機種が表示されてしまっていた(`profile.model_id`自体は正しいまま、表示だけがずれる)。`_populate_model_combo()`に`model_id`引数を追加し、`findData(model_id)`で明示的に選択し直すことで解決。

## 関連プロジェクト

- [FBSAT59](../FBSAT59) — 姉妹プロジェクト。`rigctld`/`rotctld`の**クライアント**側(接続して制御する側)。hamlibビルドCI・パッケージングスクリプトの参考元。本プロジェクトはその**サーバー起動側**を担う。
