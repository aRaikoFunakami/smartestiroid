"""XML compression utilities for Appium page source.

Appium UIAutomator2から取得したXMLページソースを圧縮し、
LLMのトークン消費を削減するためのユーティリティモジュール。
"""

import logging
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


# ============================================================
# XML圧縮ルール
# ============================================================
#
# 【基本方針：安全性最優先】
#
# LLMが操作や画面認識に必要な情報を誤って削除しないため、
# 「削除するものだけを明確に指定する」方針を採用する。
#
# - 未知の属性 → 削除しない（安全側に倒す）
# - 未知のクラス → 削除しない（安全側に倒す）
# - 迷った場合 → 削除しない
#
# ============================================================
#
# 【圧縮アルゴリズム概要】
#
# このモジュールは2段階の圧縮を行う:
#
# ■ Step 1: 属性圧縮 (_compress_element)
#
#   削除対象（明示的に指定したもののみ削除）:
#   - DELETE_ATTRIBUTES: 確実に不要な属性
#     - index, package, displayed, drawing-order, selection-start,
#       selection-end, NAF, adapter-type, instance, rotation
#   - 空文字の text, content-desc, resource-id
#   - 操作関連属性で値が "false" のもの
#     - clickable, long-clickable, scrollable, focusable,
#       checkable, dismissable が false の場合
#   - enabled="true"（デフォルト値なので冗長）
#   - checked, selected, focused, password が "false" の場合
#
#   それ以外の属性は全て保持する。
#
# ■ Step 2: 中間コンテナ削除 (_remove_redundant_containers)
#
#   以下の5条件を「すべて」満たす場合のみ削除:
#
#   1. 削除禁止ノードではない（_is_protected_node）
#      - ルート直下は削除禁止
#      - 操作関連属性がtrueのノードは削除禁止
#      - text, content-descが非空なら削除禁止
#      - resource-idが存在するなら削除禁止
#      - クラス名が操作対象（Button, EditText等）なら削除禁止
#      - 重要なコンテナクラス（ScrollView, RecyclerView等）なら削除禁止
#      - 子要素が2つ以上なら削除禁止（グルーピングとして意味がある）
#
#   2. 子要素がちょうど1つだけ
#
#   3. クラスが汎用コンテナに限定（明示的に指定）
#      - android.widget.FrameLayout
#      - android.widget.LinearLayout
#      - android.view.ViewGroup
#      - android.view.View
#      ※ 上記以外のクラスは絶対に削除しない
#
#   4. boundsが子と完全一致
#      - サイズが異なる場合はレイアウトとして意味がある
#
#   5. 子が重要なコンテナでない（_is_important_container）
#      - RecyclerView, Toolbar等の親は残す
#
# ============================================================
# 属性定義
# 参照: https://github.com/appium/appium-uiautomator2-server/blob/master/
#       app/src/main/java/io/appium/uiautomator2/utils/Attribute.java
# ============================================================

# ルート要素でのみ残す属性
ROOT_ONLY_ATTRIBUTES = {"width", "height", "rotation"}

# 確実に不要な属性（削除対象）
# UIAutomator2 Attribute.java の全属性を分類し、LLM操作判断に不要なものを削除
DELETE_ATTRIBUTES = {
    # --- レイアウト・描画関連（boundsから推測可能/冗長） ---
    "index",           # INDEX: 兄弟間の順序（boundsから推測可能）
    "package",         # PACKAGE: アプリパッケージ名（全要素で同じ）
    "displayed",       # DISPLAYED: 表示状態（画面内なら常にtrue）
    "drawing-order",   # DRAWING_ORDER: 描画順序（Z-order、操作に不要）

    # --- テキスト入力詳細（入力操作の判断には不要） ---
    "selection-start", # SELECTION_START: テキスト選択開始位置
    "selection-end",   # SELECTION_END: テキスト選択終了位置
    "input-type",      # INPUT_TYPE: 入力タイプ（数値等、操作判断に不要）
    "max-text-length", # MAX_TEXT_LENGTH: 最大テキスト長
    "multiline",       # MULTI_LINE: 複数行フラグ

    # --- アクセシビリティ関連（スクリーンリーダー向け、操作判断に不要） ---
    "a11y-important",          # IMPORTANT_FOR_ACCESSIBILITY
    "screen-reader-focusable", # SCREEN_READER_FOCUSABLE
    "a11y-focused",            # ACCESSIBILITY_FOCUSED
    "heading",                 # HEADING: 見出しフラグ
    "live-region",             # LIVE_REGION: ライブリージョン（0=none）
    "pane-title",              # PANE_TITLE: ペインタイトル
    "tooltip-text",            # TOOLTIP_TEXT: ツールチップ

    # --- 状態フラグ（UIの見た目、操作判断に不要） ---
    "showing-hint",    # SHOWING_HINT_TEXT: ヒント表示中
    "text-entry-key",  # TEXT_ENTRY_KEY: テキスト入力キー
    "context-clickable", # CONTEXT_CLICKABLE: コンテキストメニュー
    "content-invalid", # CONTENT_INVALID: 無効コンテンツフラグ

    # --- 内部/デバッグ用 ---
    "actions",         # ACTIONS: 実行可能アクションリスト（冗長）
    "window-id",       # WINDOW_ID: ウィンドウID（内部用）

    # --- 非標準属性（一部デバイス/アプリで出現） ---
    "NAF",             # Not Accessibility Friendly フラグ
    "adapter-type",    # アダプタータイプ
    "instance",        # インスタンス番号
}

# 操作関連属性（false値は削除対象）
OPERATION_ATTRIBUTES = {
    "clickable",
    "long-clickable",
    "scrollable",
    "focusable",
    "checkable",
    "dismissable",
}

# 汎用コンテナクラス（これらのみ中間コンテナ削除の対象）
# ※ ここに含まれないクラスは絶対に削除しない
GENERIC_CONTAINER_CLASSES = {
    "android.widget.FrameLayout",
    "android.widget.LinearLayout",
    "android.view.ViewGroup",
    "android.view.View",
}

# 重要なコンテナクラス（削除禁止）- 大文字小文字を区別しない部分一致
IMPORTANT_CONTAINER_PATTERNS = {
    "scrollview", "recyclerview", "listview", "viewpager",
    "toolbar", "appbar",
    "dialog", "popup", "sheet", "bottomsheet", "alert",
}

# 重要なresource-idパターン（削除禁止）
IMPORTANT_RESOURCE_ID_PATTERNS = {
    "toolbar", "header", "footer", "dialog", "popup", "sheet",
    "nav", "navigation", "menu", "content", "container",
}

# 操作対象クラス（削除禁止）
INTERACTIVE_CLASS_PATTERNS = {
    "button", "edittext", "textinput", "checkbox", "switch",
    "radiobutton", "spinner", "seekbar", "ratingbar",
}


def compress_xml(xml_source: str) -> str:
    """XMLページソースを圧縮する
    
    圧縮ルール:
    1. 不要な属性を削除（index, package, displayed, drawing-order, etc.）
    2. 空のtext, content-desc, resource-idは削除
    3. 冗長な中間コンテナを削除（安全性最優先）
    
    Args:
        xml_source: Appiumから取得した生のXML
        
    Returns:
        圧縮されたXML文字列
    """
    try:
        root = ET.fromstring(xml_source)
        
        # Step 1: 属性の圧縮
        _compress_element(root, is_root=True)
        
        # Step 2: 中間コンテナの削除（安全性最優先）
        _remove_redundant_containers(root)
        
        # XML宣言なしでシンプルに出力
        compressed = ET.tostring(root, encoding="unicode")
        return compressed
    except ET.ParseError as e:
        logger.warning(f"XML parse error during compression: {e}")
        return xml_source  # パースエラー時は元のXMLを返す


def _compress_element(elem: ET.Element, is_root: bool = False) -> None:
    """要素を再帰的に圧縮する（属性削除のみ、要素は削除しない）
    
    【方針】削除するものだけを明確に指定する
    未知の属性は削除しない（安全側に倒す）
    
    Args:
        elem: 処理対象の要素
        is_root: ルート要素かどうか
    """
    # 確実に不要な属性を削除（DELETE_ATTRIBUTESに明示されたもののみ）
    # ただしルート要素のrotationは残す
    for attr in DELETE_ATTRIBUTES:
        if attr in elem.attrib:
            if is_root and attr == "rotation":
                continue  # ルートのrotationは残す
            del elem.attrib[attr]
    
    # 空のtext, content-desc, resource-id, hintは削除（情報がないので安全）
    for attr in ["text", "content-desc", "resource-id", "hint"]:
        if elem.get(attr) == "":
            del elem.attrib[attr]
    
    # 操作関連属性で false のものは削除（trueのみ意味がある）
    for attr in OPERATION_ATTRIBUTES:
        if elem.get(attr) == "false":
            del elem.attrib[attr]
    
    # enabled="true" は冗長なので削除（デフォルト値、falseのみ意味がある）
    if elem.get("enabled") == "true":
        del elem.attrib["enabled"]
    
    # その他の状態属性で false のものも削除（falseはデフォルト状態）
    for attr in ["checked", "selected", "focused", "password"]:
        if elem.get(attr) == "false":
            del elem.attrib[attr]
    
    # 子要素を再帰的に処理
    for child in elem:
        _compress_element(child, is_root=False)


def _remove_redundant_containers(root: ET.Element) -> None:
    """冗長な中間コンテナを削除する（安全性最優先）
    
    削除条件（すべて満たす場合のみ）:
    1. 絶対に削除してはいけないノードではない
    2. 子要素がちょうど1つだけ
    3. クラスが汎用コンテナに限定
    4. boundsが子と完全一致
    5. 子が重要なコンテナでない
    
    Args:
        root: ルート要素
    """
    # 繰り返し適用（1回の走査で削除したら再度チェック）
    changed = True
    while changed:
        changed = _remove_containers_pass(root)


def _remove_containers_pass(parent: ET.Element) -> bool:
    """1回の走査で削除可能な中間コンテナを削除
    
    Returns:
        True: 何か削除した
        False: 何も削除しなかった
    """
    changed = False
    
    # 子要素のリストをコピーして走査（削除中にイテレータが壊れないように）
    children = list(parent)
    
    for child in children:
        # まず子孫を再帰的に処理
        if _remove_containers_pass(child):
            changed = True
        
        # この子が削除可能かチェック
        if _can_remove_container(child, parent):
            # 子の唯一の子（孫）を取得
            grandchild = list(child)[0]
            
            # 親の子リストでchildの位置を見つけて置換
            index = list(parent).index(child)
            parent.remove(child)
            parent.insert(index, grandchild)
            
            changed = True
    
    return changed


def _can_remove_container(node: ET.Element, parent: ET.Element) -> bool:
    """ノードを削除してよいか判定（安全性最優先）
    
    少しでも迷った場合はFalseを返す
    
    Args:
        node: 判定対象のノード
        parent: 親ノード
    
    Returns:
        True: 削除可能
        False: 削除禁止
    """
    # 条件1: 絶対に削除してはいけないノードではないこと
    if _is_protected_node(node, parent):
        return False
    
    # 条件2: 子要素がちょうど1つだけ
    children = list(node)
    if len(children) != 1:
        return False
    
    child = children[0]
    
    # 条件3: クラスが汎用コンテナに限定
    node_class = node.get("class", "")
    if node_class not in GENERIC_CONTAINER_CLASSES:
        return False
    
    # 条件4: boundsが子と完全一致
    node_bounds = node.get("bounds", "")
    child_bounds = child.get("bounds", "")
    if node_bounds != child_bounds or not node_bounds:
        return False
    
    # 条件5: 子が重要なコンテナでない
    if _is_important_container(child):
        return False
    
    # すべての条件を満たした場合のみ削除可能
    return True


def _is_protected_node(node: ET.Element, parent: ET.Element) -> bool:
    """削除禁止ノードかどうか判定
    
    Args:
        node: 判定対象のノード
        parent: 親ノード
    
    Returns:
        True: 削除禁止
        False: 削除禁止ではない（ただし他の条件も必要）
    """
    # ルート直下は削除禁止
    if parent.tag == "hierarchy":
        return True
    
    # 操作関連属性がtrueのノードは削除禁止
    for attr in ["clickable", "long-clickable", "scrollable", "focusable", 
                 "focused", "checkable", "checked", "selected", "dismissable"]:
        if node.get(attr) == "true":
            return True
    
    # text, content-descが非空なら削除禁止
    if node.get("text") or node.get("content-desc"):
        return True
    
    # resource-idが存在するなら削除禁止（空文字含む）
    if "resource-id" in node.attrib:
        return True
    
    # クラス名が操作対象なら削除禁止
    node_class = node.get("class", "").lower()
    for pattern in INTERACTIVE_CLASS_PATTERNS:
        if pattern in node_class:
            return True
    
    # 重要なコンテナクラスなら削除禁止
    if _is_important_container(node):
        return True
    
    # 子要素が2つ以上なら削除禁止（グルーピングとして意味がある）
    if len(list(node)) >= 2:
        return True
    
    return False


def _is_important_container(node: ET.Element) -> bool:
    """重要なコンテナかどうか判定
    
    Args:
        node: 判定対象のノード
    
    Returns:
        True: 重要なコンテナ
        False: 重要なコンテナではない
    """
    # クラス名をチェック
    node_class = node.get("class", "").lower()
    for pattern in IMPORTANT_CONTAINER_PATTERNS:
        if pattern in node_class:
            return True
    
    # resource-idをチェック
    resource_id = node.get("resource-id", "").lower()
    for pattern in IMPORTANT_RESOURCE_ID_PATTERNS:
        if pattern in resource_id:
            return True
    
    return False
