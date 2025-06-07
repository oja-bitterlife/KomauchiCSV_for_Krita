from krita import *
from PyQt5.QtWidgets import QFileDialog, QMessageBox
from PyQt5.Qt import qDebug, qWarning, qCritical

import csv, re

FRAME_NO_MAX = 24*60*30  # 30分まで
KEY_NO_MAX = 32  # キー番号の最大
CELL_NAMES = ["A", "B", "C", "D", "E", "F", "G", "H"]

# メッセージボックス
def showInfo(obj, title=None):
    title = str(title) if title is not None else "情報"
    QMessageBox.information(Krita.instance().activeWindow().qwindow(), str(title), str(obj))
def showWarn(obj, title=None):
    title = str(title) if title is not None else "警告"
    QMessageBox.warning(Krita.instance().activeWindow().qwindow(), str(title), str(obj))
def showError(obj, title=None):
    title = str(title) if title is not None else "エラー"
    QMessageBox.critical(Krita.instance().activeWindow().qwindow(), str(title), str(obj))

# ロギング
def logDebug(obj):
    qDebug(str(obj).encode('utf-8'))
def logWarn(obj):
    qWarning(str(obj).encode('utf-8'))
def logError(obj):
    qCritical(str(obj).encode('utf-8'))


# 各セルのキー番号がどのレイヤーに対応するかを管理する
class TargetLayer:
    def __init__(self, doc):
        self.data = [[None] * KEY_NO_MAX for _ in range(len(CELL_NAMES))]
        self.krita_layers = {}

        # Kritaのレイヤーノードを再帰的に収集するヘルパー関数
        def _collect_layers(node):
            if node.type() == 'grouplayer': # グループレイヤーの場合
                for child in node.childNodes():
                    _collect_layers(child) # 子ノードも再帰的に収集
            elif node.type() == 'clonelayer': # クローンレイヤだけ回収する
                self.krita_layers[node.name()] = node # レイヤー名をキー、レイヤーノードを値として格納
        _collect_layers(doc.rootNode()) # ドキュメントのルートノードからレイヤー収集を開始

    def setTarget(self, key_no, cell_index, layer_name):
        # ターゲットレイヤーを設定
        self.data[cell_index][key_no] = self.krita_layers[layer_name]

    def __repr__(self) -> str:
        return "\n".join([f"{CELL_NAMES[i]}: {str([cell_target.name() if cell_target is not None else None for cell_target in keys])}" for i,keys in enumerate(self.data)])

    def getLayer(self, cell_index, key_no):
        return self.data[cell_index][key_no]

    def getTargetList(self, cell_index):
        return self.data[cell_index]


# フレームごとの各セルのキー番号情報を管理する
class KeyframeGrid:
    def __init__(self, doc):
        self.data = []

    # フレームのセルのキーを保存
    def setKey(self, frame_no, cell_index, key_no):
        # 入力チェック
        if key_no < 0 or key_no >= KEY_NO_MAX:
            raise ValueError(f"KeyNo Error: {key_no}")
        if cell_index < 0 or cell_index >= len(CELL_NAMES):
            raise ValueError(f"CellIndex Error: {cell_index}")
        if frame_no < 0 or frame_no >= FRAME_NO_MAX:
            raise ValueError(f"FrameNo Error: {frame_no}")

        # frame_noが入るようサイズを増やしておく
        if len(self.data) <= frame_no:
            self.data.extend([[None] * len(CELL_NAMES) for _ in range(frame_no - len(self.data) + 1)])

        # キーを設定
        self.data[frame_no][cell_index] = key_no

    # セルのキーを全フレームまとめて返す
    def getCellkeys(self, cell_index):
        return [cells[cell_index] for cells in self.data]

    # セルのキーと対応するレイヤーが全部あるかチェックする
    def check_target(self, target_layers):
        for frame in self.data:
            for i, key_no in enumerate(frame):
                if key_no is not None:
                    if target_layers.getLayer(i, key_no) is None:
                        raise ValueError(f"{CELL_NAMES[i]}:{key_no} のレイヤーが設定されていません")

    def __repr__(self) -> str:
        return "\n".join(f"{i}: {str(frame)}" for i, frame in enumerate(self.data))


# 本体
class KomauchiFromCSV(Extension):

    def __init__(self, parent):
        super().__init__(parent)

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
            showWarn("先にドキュメントを開いてください")
            return
        doc_path = doc.fileName()

        csv_file_path, _ = QFileDialog.getOpenFileName(Krita.instance().activeWindow().qwindow(), 
                                                    "Select Komauchi CSV File", 
                                                    doc_path,
                                                    "CSV Files (*.csv);;All Files (*)")
        if not csv_file_path:
            showInfo("実行を中止しました")
            return

        try:
            target_layers = TargetLayer(doc)
            keyframe_grid = KeyframeGrid(doc)

            with open(csv_file_path, 'r', encoding='utf-8') as f:
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
                        self.load_setting(rows, target_layers)
                        continue

                    # 4. データ行
                    for i, key in enumerate(rows[1:]):
                        if not key:
                            continue
                        keyframe_grid.setKey(int(rows[0]), i, int(key))

            # 設定確認
            logDebug(target_layers)
            logDebug(keyframe_grid)
            keyframe_grid.check_target(target_layers)

            # アニメーションの準備
            self.setup_animation(doc, target_layers)

            # キーフレームを適用
            self.apply_keyframes(doc, target_layers, keyframe_grid)

        except FileNotFoundError:
            showError(f"CSVファイルを開けませんでした: {csv_file_path}")
            return

        except Exception as e:
            showError(e)
            return


    # @設定の解析
    def load_setting(self, rows, target_layers):
        if rows[0].upper() == "@CELL":
            cell_name = rows[1].upper()

            if cell_name not in CELL_NAMES:
                raise ValueError(f"{cell_name} はセル名として使えません")

            cell_index = CELL_NAMES.index(cell_name)
            for i, layer_name in enumerate(rows[2:]):
                if not layer_name:
                    continue
                target_layers.setTarget(i+1, cell_index, layer_name)
            return

        showWarn(f"未対応の設定です: {rows[0]}")


    # アニメーションの準備
    def setup_animation(self, doc, target_layers):
        doc.setCurrentTime(0)
        instance = Krita.instance()

        for cell_index in range(len(CELL_NAMES)):
            for target_layer in target_layers.getTargetList(cell_index):
                if target_layer is None:
                    continue

                # 0フレーム目にopacity:255でキーを打つ(初期化)
                doc.setActiveNode(target_layer)
                instance.action('add_scalar_keyframes').trigger()
                target_layer.setOpacity(255)
                doc.refreshProjection()  # これをしないと落ちる


    # キーフレームの設定
    def apply_keyframes(self, doc, target_layers, keyframe_grid):
        # セルごとに処理をする(フレームごとではない)
        for cell_index in range(len(CELL_NAMES)):
            befor_key_no = None

            # 同じセルをフレームごとに処理する
            for frame_no, key_no in enumerate(keyframe_grid.getCellkeys(cell_index)):
                # 0フレーム目は特別なので処理しない
                if frame_no == 0:
                    continue

                # タイムラインの設定
                doc.setCurrentTime(frame_no)

                # セルの対象レイヤ全てを一旦消す
                for layer in target_layers.getTargetList(cell_index):
                    if layer is not None:
                        layer.setOpacity(0)

                # 設定するレイヤの取得
                if key_no is None:
                    # 前の続き
                    key_no = befor_key_no
                else:
                    # 更新
                    befor_key_no = key_no

                # # 対象レイヤを表示する
                if key_no is not None:
                    target_layer = target_layers.getLayer(cell_index, key_no)
                    target_layer.setOpacity(255)

Krita.instance().addExtension(KomauchiFromCSV(Krita.instance()))



