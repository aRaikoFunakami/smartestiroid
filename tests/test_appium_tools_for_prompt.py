"""appium_tools_for_prompt のテスト（Android接続不要）"""

import pytest
from smartestiroid.appium_tools import appium_tools_for_prompt, appium_tools


def test_appium_tools_for_prompt_returns_string():
    """appium_tools_for_prompt が文字列を返すことを確認"""
    result = appium_tools_for_prompt()
    assert isinstance(result, str)
    assert len(result) > 0


def test_appium_tools_for_prompt_contains_all_tools():
    """全ツールの名前が含まれていることを確認"""
    tools = appium_tools()
    result = appium_tools_for_prompt()
    
    # 各ツール名が結果に含まれているか確認
    for tool in tools:
        assert tool.name in result, f"ツール '{tool.name}' が結果に含まれていません"


def test_appium_tools_for_prompt_contains_descriptions():
    """各ツールの説明が含まれていることを確認"""
    tools = appium_tools()
    result = appium_tools_for_prompt()
    
    # 各ツールの説明が含まれているか確認（最初の50文字程度）
    for tool in tools:
        desc_preview = tool.description[:30] if len(tool.description) > 30 else tool.description
        assert desc_preview in result, f"ツール '{tool.name}' の説明が結果に含まれていません"


def test_appium_tools_for_prompt_format():
    """出力フォーマットが正しいことを確認"""
    result = appium_tools_for_prompt()
    lines = result.split('\n')
    
    # 各ツールが "# ツール名" で始まることを確認
    tool_lines = [line for line in lines if line.startswith('# ')]
    assert len(tool_lines) > 0, "ツール行が見つかりません"
    
    # 最初のツール行の形式を確認
    first_tool_line = tool_lines[0]
    assert first_tool_line.startswith('# '), "ツール名が '# ' で始まっていません"


def test_appium_tools_for_prompt_includes_parameters():
    """パラメータ情報が含まれていることを確認"""
    result = appium_tools_for_prompt()
    
    # パラメータを持つツール（click_element）の情報を確認
    assert 'click_element' in result
    
    # パラメータ情報のキーワードが含まれているか確認
    # （全ツールがパラメータを持つわけではないが、少なくとも一部は持つ）
    has_param_info = ('Parameters:' in result or 
                      'required' in result or 
                      'optional' in result)
    assert has_param_info, "パラメータ情報が見つかりません"


def test_appium_tools_for_prompt_specific_tool():
    """特定のツール（click_element）の情報が正しく含まれているか確認"""
    result = appium_tools_for_prompt()
    
    # click_element ツールの情報を確認
    assert 'click_element' in result
    assert 'xpath' in result.lower() or 'XPath' in result
    
    # パラメータ情報が含まれているか確認
    lines = result.split('\n')
    in_click_element = False
    found_xpath_param = False
    
    for line in lines:
        if 'click_element' in line:
            in_click_element = True
        if in_click_element and 'xpath' in line.lower():
            found_xpath_param = True
            break
    
    assert found_xpath_param, "click_element の xpath パラメータ情報が見つかりません"


def test_appium_tools_for_prompt_tool_count():
    """appium_tools() と同じ数のツールが含まれていることを確認"""
    tools = appium_tools()
    result = appium_tools_for_prompt()
    
    # "# " で始まる行（ツール名行）をカウント
    tool_lines = [line for line in result.split('\n') if line.startswith('# ')]
    
    assert len(tool_lines) == len(tools), \
        f"ツール数が一致しません（期待: {len(tools)}, 実際: {len(tool_lines)}）"


def test_appium_tools_for_prompt_no_error():
    """appium_tools_for_prompt が例外を発生させないことを確認"""
    try:
        result = appium_tools_for_prompt()
        assert result is not None
    except Exception as e:
        pytest.fail(f"appium_tools_for_prompt が例外を発生させました: {e}")


def test_appium_tools_for_prompt_multiline():
    """複数行の出力であることを確認"""
    result = appium_tools_for_prompt()
    lines = result.split('\n')
    
    # 少なくとも10行以上の出力があることを確認（ツール数が多いため）
    assert len(lines) >= 10, f"出力行数が少なすぎます（実際: {len(lines)}行）"


def test_appium_tools_for_prompt_parameter_details():
    """パラメータの詳細情報（型、必須/任意）が含まれているか確認"""
    result = appium_tools_for_prompt()
    
    # パラメータ情報のフォーマットを確認
    has_type_info = 'string' in result or 'integer' in result or 'boolean' in result
    has_required_info = 'required' in result or 'optional' in result
    
    # 少なくともどちらか一方は含まれているはず
    assert has_type_info or has_required_info, \
        "パラメータの型情報または必須/任意情報が見つかりません"
