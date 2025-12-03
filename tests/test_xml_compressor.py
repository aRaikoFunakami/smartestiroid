"""Tests for xml_compressor module.

このテストはAppiumやAndroid端末に依存せず、純粋にXML圧縮ロジックをテストします。
xml_compressor.pyを修正した場合は、このテストが100%パスすることを確認してください。

【重要】圧縮アルゴリズムの基本方針:
- 削除するものだけを明確に指定する
- 未知の属性やクラスは削除しない（安全側に倒す）
"""

import pytest
from smartestiroid.appium_tools.xml_compressor import (
    compress_xml,
    _compress_element,
    _remove_redundant_containers,
    _can_remove_container,
    _is_protected_node,
    _is_important_container,
    DELETE_ATTRIBUTES,
    ROOT_ONLY_ATTRIBUTES,
    OPERATION_ATTRIBUTES,
    GENERIC_CONTAINER_CLASSES,
    IMPORTANT_CONTAINER_PATTERNS,
    IMPORTANT_RESOURCE_ID_PATTERNS,
    INTERACTIVE_CLASS_PATTERNS,
)
from xml.etree import ElementTree as ET


class TestConstants:
    """定数の定義テスト"""

    def test_delete_attributes_contains_known_unnecessary(self):
        """削除対象属性が定義されているか確認"""
        expected = {"index", "package", "displayed", "drawing-order"}
        assert expected.issubset(DELETE_ATTRIBUTES)

    def test_operation_attributes(self):
        """操作関連属性（false削除対象）が定義されているか確認"""
        expected = {"clickable", "scrollable", "focusable", "checkable"}
        assert expected.issubset(OPERATION_ATTRIBUTES)

    def test_root_only_attributes(self):
        """ルート専用属性の確認"""
        assert ROOT_ONLY_ATTRIBUTES == {"width", "height", "rotation"}

    def test_generic_container_classes(self):
        """汎用コンテナクラスの確認"""
        expected = {
            "android.widget.FrameLayout",
            "android.widget.LinearLayout",
            "android.view.ViewGroup",
            "android.view.View",
        }
        assert GENERIC_CONTAINER_CLASSES == expected

    def test_important_container_patterns(self):
        """重要コンテナパターンにRecyclerView等が含まれる"""
        assert "recyclerview" in IMPORTANT_CONTAINER_PATTERNS
        assert "scrollview" in IMPORTANT_CONTAINER_PATTERNS
        assert "toolbar" in IMPORTANT_CONTAINER_PATTERNS


class TestSafetyFirstPolicy:
    """安全性最優先ポリシーのテスト（未知の属性・クラスを削除しない）"""

    def test_unknown_attributes_are_preserved(self):
        """未知の属性は削除されない"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
          <android.widget.Button 
            class="android.widget.Button"
            text="OK"
            bounds="[0,0][100,50]"
            unknown-attr="some-value"
            new-feature="enabled"
            custom-data="test123" />
        </hierarchy>"""
        
        result = compress_xml(xml)
        
        # 未知の属性は保持される
        assert 'unknown-attr="some-value"' in result
        assert 'new-feature="enabled"' in result
        assert 'custom-data="test123"' in result

    def test_unknown_class_is_not_removed(self):
        """未知のクラスのコンテナは削除されない"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
  <com.custom.NewContainerWidget class="com.custom.NewContainerWidget" bounds="[0,0][1080,1920]">
    <android.widget.Button text="OK" bounds="[0,0][1080,1920]" clickable="true" />
  </com.custom.NewContainerWidget>
</hierarchy>"""
        
        result = compress_xml(xml)
        
        # カスタムクラスは削除されない
        assert "com.custom.NewContainerWidget" in result

    def test_future_appium_attributes_preserved(self):
        """将来のAppiumバージョンで追加される属性も保持される"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
          <android.widget.Button 
            class="android.widget.Button"
            text="OK"
            bounds="[0,0][100,50]"
            accessibility-pane-title="Main"
            tooltip="Click here"
            state-description="Active" />
        </hierarchy>"""
        
        result = compress_xml(xml)
        
        # 新しい属性は保持される
        assert 'accessibility-pane-title="Main"' in result
        assert 'tooltip="Click here"' in result
        assert 'state-description="Active"' in result


class TestAttributeCompression:
    """属性圧縮のテスト（Step 1）"""

    def test_removes_explicitly_defined_unnecessary_attributes(self):
        """明示的に定義された不要属性のみが削除される"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
          <android.widget.Button 
            class="android.widget.Button"
            resource-id="btn1"
            text="OK"
            bounds="[0,0][100,50]"
            index="0"
            package="com.example"
            displayed="true"
            drawing-order="1"
            clickable="true" />
        </hierarchy>"""
        
        result = compress_xml(xml)
        
        # 保持すべき属性が残っている
        assert 'class="android.widget.Button"' in result
        assert 'resource-id="btn1"' in result
        assert 'text="OK"' in result
        assert 'bounds="[0,0][100,50]"' in result
        assert 'clickable="true"' in result
        
        # DELETE_ATTRIBUTESで定義された属性のみ削除されている
        assert 'index=' not in result
        assert 'package=' not in result
        assert 'displayed=' not in result
        assert 'drawing-order=' not in result

    def test_removes_empty_text_attributes(self):
        """空のtext, content-desc, resource-idが削除される"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
          <android.widget.TextView 
            class="android.widget.TextView"
            text=""
            content-desc=""
            resource-id=""
            bounds="[0,0][100,50]" />
        </hierarchy>"""
        
        result = compress_xml(xml)
        
        # 空の属性は削除される
        assert 'text=""' not in result
        assert 'content-desc=""' not in result
        assert 'resource-id=""' not in result
        # classとboundsは残る
        assert 'class=' in result
        assert 'bounds=' in result

    def test_removes_false_operation_attributes(self):
        """操作関連属性のfalse値が削除される"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
          <android.widget.TextView 
            class="android.widget.TextView"
            text="Hello"
            bounds="[0,0][100,50]"
            clickable="false"
            scrollable="false"
            focusable="false" />
        </hierarchy>"""
        
        result = compress_xml(xml)
        
        assert 'clickable="false"' not in result
        assert 'scrollable="false"' not in result
        assert 'focusable="false"' not in result
        assert 'text="Hello"' in result

    def test_keeps_true_operation_attributes(self):
        """操作関連属性のtrue値は保持される"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
          <android.widget.Button 
            class="android.widget.Button"
            text="Click me"
            bounds="[0,0][100,50]"
            clickable="true"
            focusable="true" />
        </hierarchy>"""
        
        result = compress_xml(xml)
        
        assert 'clickable="true"' in result
        assert 'focusable="true"' in result

    def test_removes_enabled_true(self):
        """enabled="true"は冗長なので削除される"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
          <android.widget.Button 
            class="android.widget.Button"
            bounds="[0,0][100,50]"
            enabled="true" />
        </hierarchy>"""
        
        result = compress_xml(xml)
        assert 'enabled="true"' not in result

    def test_keeps_enabled_false(self):
        """enabled="false"は意味があるので保持される"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
          <android.widget.Button 
            class="android.widget.Button"
            bounds="[0,0][100,50]"
            enabled="false" />
        </hierarchy>"""
        
        result = compress_xml(xml)
        assert 'enabled="false"' in result

    def test_keeps_hint_attribute(self):
        """hint属性は保持される"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
          <android.widget.EditText 
            class="android.widget.EditText"
            bounds="[0,0][100,50]"
            hint="Enter your name" />
        </hierarchy>"""
        
        result = compress_xml(xml)
        assert 'hint="Enter your name"' in result

    def test_root_keeps_width_height_rotation(self):
        """ルート要素はwidth, height, rotationを保持"""
        xml = """<hierarchy rotation="0" width="1080" height="1920" package="com.example">
          <android.widget.Button bounds="[0,0][100,50]" />
        </hierarchy>"""
        
        result = compress_xml(xml)
        
        assert 'rotation="0"' in result
        assert 'width="1080"' in result
        assert 'height="1920"' in result
        assert 'package=' not in result


class TestContainerRemoval:
    """中間コンテナ削除のテスト（Step 2）"""

    def test_removes_redundant_single_child_containers(self):
        """冗長な単一子コンテナが削除される"""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0" width="1080" height="1920">
  <android.widget.FrameLayout class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
    <android.widget.LinearLayout class="android.widget.LinearLayout" bounds="[0,0][1080,1920]">
      <android.widget.FrameLayout class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
        <android.widget.LinearLayout class="android.widget.LinearLayout" bounds="[0,0][1080,1920]">
          <android.widget.Button text="OK" bounds="[100,100][200,150]" clickable="true" />
        </android.widget.LinearLayout>
      </android.widget.FrameLayout>
    </android.widget.LinearLayout>
  </android.widget.FrameLayout>
</hierarchy>"""
        
        result = compress_xml(xml)
        
        # Buttonは必ず残る
        assert "Button" in result
        assert 'text="OK"' in result
        
        # 元のXMLより短くなっている（圧縮されている）
        assert len(result) < len(xml)

    def test_keeps_container_with_resource_id(self):
        """resource-idを持つコンテナは削除されない"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
  <android.widget.FrameLayout class="android.widget.FrameLayout" 
    resource-id="com.example:id/container" bounds="[0,0][1080,1920]">
    <android.widget.Button text="OK" bounds="[0,0][1080,1920]" clickable="true" />
  </android.widget.FrameLayout>
</hierarchy>"""
        
        result = compress_xml(xml)
        
        # resource-idを持つコンテナは残る
        assert 'resource-id="com.example:id/container"' in result
        assert "FrameLayout" in result

    def test_keeps_container_with_different_bounds(self):
        """boundsが子と異なるコンテナは削除されない"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
  <android.widget.FrameLayout class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
    <android.widget.Button text="OK" bounds="[100,100][200,150]" clickable="true" />
  </android.widget.FrameLayout>
</hierarchy>"""
        
        result = compress_xml(xml)
        
        # boundsが異なるのでFrameLayoutは残る
        assert "FrameLayout" in result

    def test_keeps_scrollable_container(self):
        """scrollable="true"のコンテナは削除されない"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
  <android.widget.FrameLayout class="android.widget.FrameLayout" 
    bounds="[0,0][1080,1920]" scrollable="true">
    <android.widget.TextView text="Content" bounds="[0,0][1080,1920]" />
  </android.widget.FrameLayout>
</hierarchy>"""
        
        result = compress_xml(xml)
        
        assert "FrameLayout" in result
        assert 'scrollable="true"' in result

    def test_keeps_container_with_multiple_children(self):
        """複数の子を持つコンテナは削除されない"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
  <android.widget.LinearLayout class="android.widget.LinearLayout" bounds="[0,0][1080,1920]">
    <android.widget.Button text="OK" bounds="[0,0][540,100]" clickable="true" />
    <android.widget.Button text="Cancel" bounds="[540,0][1080,100]" clickable="true" />
  </android.widget.LinearLayout>
</hierarchy>"""
        
        result = compress_xml(xml)
        
        # 複数の子を持つのでLinearLayoutは残る
        assert "LinearLayout" in result
        assert 'text="OK"' in result
        assert 'text="Cancel"' in result

    def test_keeps_recyclerview_parent(self):
        """RecyclerViewの親コンテナは削除されない"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
  <android.widget.FrameLayout class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
    <androidx.recyclerview.widget.RecyclerView class="androidx.recyclerview.widget.RecyclerView" 
      bounds="[0,0][1080,1920]" scrollable="true">
      <android.widget.TextView text="Item" bounds="[0,0][1080,100]" />
    </androidx.recyclerview.widget.RecyclerView>
  </android.widget.FrameLayout>
</hierarchy>"""
        
        result = compress_xml(xml)
        
        # RecyclerViewの親FrameLayoutは残る
        assert "FrameLayout" in result
        assert "RecyclerView" in result

    def test_keeps_toolbar_parent(self):
        """Toolbarの親コンテナは削除されない"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
  <android.widget.FrameLayout class="android.widget.FrameLayout" bounds="[0,0][1080,200]">
    <androidx.appcompat.widget.Toolbar class="androidx.appcompat.widget.Toolbar" 
      bounds="[0,0][1080,200]">
      <android.widget.TextView text="Title" bounds="[100,50][500,150]" />
    </androidx.appcompat.widget.Toolbar>
  </android.widget.FrameLayout>
</hierarchy>"""
        
        result = compress_xml(xml)
        
        assert "FrameLayout" in result
        assert "Toolbar" in result

    def test_keeps_root_direct_children(self):
        """ルート直下のコンテナは削除されない"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
  <android.widget.FrameLayout class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
    <android.widget.Button text="OK" bounds="[0,0][1080,1920]" clickable="true" />
  </android.widget.FrameLayout>
</hierarchy>"""
        
        result = compress_xml(xml)
        
        # ルート直下のFrameLayoutは残る
        assert "FrameLayout" in result


class TestIsProtectedNode:
    """_is_protected_node関数のテスト"""

    def test_root_direct_child_is_protected(self):
        """ルート直下のノードは保護される"""
        root = ET.fromstring('<hierarchy><node /></hierarchy>')
        node = root[0]
        assert _is_protected_node(node, root) is True

    def test_clickable_node_is_protected(self):
        """clickable="true"のノードは保護される"""
        root = ET.fromstring('<parent><node clickable="true" /></parent>')
        node = root[0]
        assert _is_protected_node(node, root) is True

    def test_node_with_text_is_protected(self):
        """textを持つノードは保護される"""
        root = ET.fromstring('<parent><node text="Hello" /></parent>')
        node = root[0]
        assert _is_protected_node(node, root) is True

    def test_node_with_resource_id_is_protected(self):
        """resource-idを持つノードは保護される"""
        root = ET.fromstring('<parent><node resource-id="id" /></parent>')
        node = root[0]
        assert _is_protected_node(node, root) is True

    def test_node_with_multiple_children_is_protected(self):
        """複数の子を持つノードは保護される"""
        root = ET.fromstring('<parent><node><child1 /><child2 /></node></parent>')
        node = root[0]
        assert _is_protected_node(node, root) is True

    def test_button_class_is_protected(self):
        """Buttonクラスは保護される"""
        root = ET.fromstring('<parent><node class="android.widget.Button" /></parent>')
        node = root[0]
        assert _is_protected_node(node, root) is True


class TestIsImportantContainer:
    """_is_important_container関数のテスト"""

    def test_recyclerview_is_important(self):
        """RecyclerViewは重要なコンテナ"""
        elem = ET.fromstring('<node class="androidx.recyclerview.widget.RecyclerView" />')
        assert _is_important_container(elem) is True

    def test_scrollview_is_important(self):
        """ScrollViewは重要なコンテナ"""
        elem = ET.fromstring('<node class="android.widget.ScrollView" />')
        assert _is_important_container(elem) is True

    def test_toolbar_is_important(self):
        """Toolbarは重要なコンテナ"""
        elem = ET.fromstring('<node class="androidx.appcompat.widget.Toolbar" />')
        assert _is_important_container(elem) is True

    def test_dialog_resource_id_is_important(self):
        """dialog関連のresource-idは重要"""
        elem = ET.fromstring('<node resource-id="com.example:id/dialog_container" />')
        assert _is_important_container(elem) is True

    def test_framelayout_is_not_important(self):
        """FrameLayoutは重要なコンテナではない"""
        elem = ET.fromstring('<node class="android.widget.FrameLayout" />')
        assert _is_important_container(elem) is False


class TestCanRemoveContainer:
    """_can_remove_container関数のテスト"""

    def test_can_remove_simple_wrapper(self):
        """単純なラッパーコンテナは削除可能"""
        root = ET.fromstring('''
        <parent>
          <android.widget.FrameLayout class="android.widget.FrameLayout" bounds="[0,0][100,100]">
            <android.widget.TextView class="android.widget.TextView" bounds="[0,0][100,100]" />
          </android.widget.FrameLayout>
        </parent>''')
        node = root[0]
        assert _can_remove_container(node, root) is True

    def test_cannot_remove_with_different_bounds(self):
        """boundsが異なる場合は削除不可"""
        root = ET.fromstring('''
        <parent>
          <android.widget.FrameLayout class="android.widget.FrameLayout" bounds="[0,0][100,100]">
            <android.widget.TextView class="android.widget.TextView" bounds="[10,10][90,90]" />
          </android.widget.FrameLayout>
        </parent>''')
        node = root[0]
        assert _can_remove_container(node, root) is False

    def test_cannot_remove_with_resource_id(self):
        """resource-idがある場合は削除不可"""
        root = ET.fromstring('''
        <parent>
          <android.widget.FrameLayout class="android.widget.FrameLayout" 
            resource-id="container" bounds="[0,0][100,100]">
            <android.widget.TextView class="android.widget.TextView" bounds="[0,0][100,100]" />
          </android.widget.FrameLayout>
        </parent>''')
        node = root[0]
        assert _can_remove_container(node, root) is False

    def test_cannot_remove_non_generic_container(self):
        """汎用コンテナ以外は削除不可"""
        root = ET.fromstring('''
        <parent>
          <android.widget.RelativeLayout class="android.widget.RelativeLayout" bounds="[0,0][100,100]">
            <android.widget.TextView class="android.widget.TextView" bounds="[0,0][100,100]" />
          </android.widget.RelativeLayout>
        </parent>''')
        node = root[0]
        assert _can_remove_container(node, root) is False


class TestCompressionRatio:
    """圧縮率のテスト"""

    def test_significant_compression(self):
        """十分な圧縮が行われる"""
        # 典型的な冗長なXML
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0" width="1080" height="1920">
  <android.widget.FrameLayout class="android.widget.FrameLayout" 
    index="0" package="com.example" bounds="[0,0][1080,1920]"
    clickable="false" focusable="false" scrollable="false" displayed="true">
    <android.widget.LinearLayout class="android.widget.LinearLayout" 
      index="0" package="com.example" bounds="[0,0][1080,1920]"
      clickable="false" focusable="false" scrollable="false" displayed="true">
      <android.widget.FrameLayout class="android.widget.FrameLayout" 
        index="0" package="com.example" bounds="[0,0][1080,1920]"
        clickable="false" focusable="false" scrollable="false" displayed="true">
        <android.widget.Button class="android.widget.Button"
          index="0" package="com.example" bounds="[100,100][200,150]"
          text="OK" clickable="true" focusable="true" displayed="true" />
      </android.widget.FrameLayout>
    </android.widget.LinearLayout>
  </android.widget.FrameLayout>
</hierarchy>"""
        
        result = compress_xml(xml)
        
        compression_ratio = (1 - len(result) / len(xml)) * 100
        # 少なくとも30%は圧縮されるべき
        assert compression_ratio > 30, f"Compression ratio was only {compression_ratio:.1f}%"


class TestEdgeCases:
    """エッジケースのテスト"""

    def test_invalid_xml_returns_original(self):
        """不正なXMLは元のまま返す"""
        invalid_xml = "<not valid xml"
        result = compress_xml(invalid_xml)
        assert result == invalid_xml

    def test_empty_hierarchy(self):
        """空のhierarchy"""
        xml = '<hierarchy rotation="0" width="1080" height="1920" />'
        result = compress_xml(xml)
        assert 'hierarchy' in result

    def test_deeply_nested_structure(self):
        """深くネストした構造でも動作する"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
  <android.widget.FrameLayout class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
    <android.widget.FrameLayout class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
      <android.widget.FrameLayout class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
        <android.widget.FrameLayout class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
          <android.widget.FrameLayout class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
            <android.widget.Button text="Deep" bounds="[0,0][1080,1920]" clickable="true" />
          </android.widget.FrameLayout>
        </android.widget.FrameLayout>
      </android.widget.FrameLayout>
    </android.widget.FrameLayout>
  </android.widget.FrameLayout>
</hierarchy>"""
        
        result = compress_xml(xml)
        
        # Buttonは必ず残る
        assert 'text="Deep"' in result
        # エラーなく完了
        assert result is not None

    def test_special_characters_in_text(self):
        """テキストに特殊文字が含まれる場合"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
  <android.widget.TextView class="android.widget.TextView" 
    text="Hello &amp; World &lt;test&gt;" bounds="[0,0][100,50]" />
</hierarchy>"""
        
        result = compress_xml(xml)
        
        # 特殊文字がエスケープされて保持される
        assert "&amp;" in result or "& " in result
        assert "Hello" in result

    def test_japanese_text(self):
        """日本語テキストが正しく処理される"""
        xml = """<hierarchy rotation="0" width="1080" height="1920">
  <android.widget.TextView class="android.widget.TextView" 
    text="こんにちは" bounds="[0,0][100,50]" />
</hierarchy>"""
        
        result = compress_xml(xml)
        
        assert "こんにちは" in result
