from krita import *
from PyQt5.QtWidgets import QFileDialog, QMessageBox
import csv, re

FRAME_NO_MAX = 65536
CELLS = ["A", "B", "C", "D"]

# メッセージボックス
def showInfo(title, obj):
    QMessageBox.information(
        Krita.instance().activeWindow().qwindow(),
        title,
        str(obj)
    )
def showWarn(title, obj):
    QMessageBox.warning(
        Krita.instance().activeWindow().qwindow(),
        title,
        str(obj)
    )
def showError(title, obj):
    QMessageBox.critical(
        Krita.instance().activeWindow().qwindow(),
        title,
        str(obj)
    )


class MyExtension(Extension):

    def __init__(self, parent):
        # これは親クラスを初期化します。サブクラス化の際に重要です。
        super().__init__(parent)
        self.target_layers = {cell: {} for cell in CELLS }

    def setup(self):
        pass

    def createActions(self, window):
        action = window.createAction("oja_komauchi", "コマ打ち from CSV", "tools/scripts")
        action.triggered.connect(self.import_csv)

    def import_csv(self):
        # 現在開いているファイル
        doc = Krita.instance().activeDocument()
        if not doc:
            # ファイルを開いていない
            showWarn("ドキュメントがありません", "先にドキュメントを開いてください")
            return
        doc_path = doc.fileName()

        csv_file_path, _ = QFileDialog.getOpenFileName(Krita.instance().activeWindow().qwindow(), 
                                                    "Select Komauchi CSV File", 
                                                    doc_path,
                                                    "CSV Files (*.csv);;All Files (*)")
        if not csv_file_path:
            showWarn("キャンセル", "実行を中止しました")
            return


        self.krita_layers = {}
        # Kritaのレイヤーノードを再帰的に収集するヘルパー関数
        def _collect_layers(node):
            if node.type() == 'grouplayer': # グループレイヤーの場合
                for child in node.childNodes():
                    _collect_layers(child) # 子ノードも再帰的に収集
            elif node.type() == 'clonelayer': # クローンレイヤだけ回収
                self.krita_layers[node.name()] = node # レイヤー名をキー、レイヤーノードを値として格納
        _collect_layers(doc.rootNode()) # ドキュメントのルートノードからレイヤー収集を開始


        try:
            with open(csv_file_path, 'r', encoding='utf-8') as f:
                keyframes = []

                for rows in csv.reader(f):
                    # 1. 空行をスキップ
                    if not rows:
                        continue

                    # 前後空白削除
                    rows = [cell.strip() for cell in rows]

                    # 空セルチェック
                    if len(rows) == 0 or not rows[0]:
                        continue

                    # 2. コメント行をスキップ
                    if rows[0].startswith('#'):
                        continue

                    # 3. 設定行の解析
                    if rows[0].startswith('@'):
                        # 設定の取得
                        self.load_setting(rows)
                        continue

                    # 4. データ行
                    frame_no = int(rows[0])
                    if frame_no < 0 or frame_no >= FRAME_NO_MAX:
                        raise Exception(f"FrameNo Error: {rows[0]}")

                    # frame_noが入るようサイズを増やしておく
                    if len(keyframes) <= frame_no:
                        keyframes.extend([None] * (frame_no - len(keyframes) + 1))

                    keyframes[frame_no] = [int(key) if key.isdigit() else None for key in rows[1:]]

            # アニメーションの準備
            self.setup_animation(doc)

            # キーフレームを適用
            self.apply_keyframes(doc, keyframes)

            # 設定確認
            # for k, v in self.settings.items():
            #     showInfo(k, v)

        except FileNotFoundError:
            showError("エラー", f"CSVファイルを開けませんでした: {csv_file_path}")
            return {}, []

        except Exception as e:
            showError("エラー", str(e))
            return {}, []


    # @設定の解析
    def load_setting(self, rows):
        m = re.match(r"@([A-Z]?)(\d?)$", rows[0])
        if m:
            cell,key = m.groups()[:2]
            if cell and key:
                self.target_layers[cell][key] = rows[1]
                return

        showWarn("未対応", f"未対応の設定です: {rows[0]}")


    # アニメーションの準備
    def setup_animation(self, doc):
        doc.setCurrentTime(0)
        instance = Krita.instance()

        for cell in CELLS:
            for target_key, target_layer_name in self.target_layers[cell].items():
                if target_layer_name is not None:
                    target_layer = self.krita_layers[target_layer_name]

                    # 0フレーム目にopacity:255でキーを打つ(初期化)
                    doc.setActiveNode(target_layer)
                    instance.action('add_scalar_keyframes').trigger()
                    target_layer.setOpacity(255)
                    doc.refreshProjection()  # これをしないと落ちる

    # キーフレームの設定
    def apply_keyframes(self, doc, keyframes):
        for frame_no, keyframe in enumerate(keyframes):
            # Frameスキップ
            if keyframe is None:
                continue

            doc.setCurrentTime(frame_no)

            # Frameに含まれるキー
            for j, keyframe_key in enumerate(keyframe):
                if keyframe_key is None:
                    # キーがあれば消去
                    continue
                cell = CELLS[j]

                for target_key, target_layer_name in self.target_layers[cell].items():
                    target_layer = self.krita_layers.get(target_layer_name)
                    if target_layer is None:
                        raise Exception(f"対象レイヤーが見つかりません: {target_layer_name}")

                    target_layer.setOpacity(255*int(target_key)//255)

Krita.instance().addExtension(MyExtension(Krita.instance()))



