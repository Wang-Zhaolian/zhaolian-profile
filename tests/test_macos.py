from __future__ import annotations
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest

from academic_profile import chatgpt_auth, library, file_inputs
from academic_profile.chatgpt_auth import AIServiceError, MacKeychainProtector


class MemoryKeychain:
    def __init__(self):
        self.values = {}

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, value):
        self.values[service, account] = value


def test_mac_keychain_encryption_and_restart():
    backend = MemoryKeychain()
    first = MacKeychainProtector(backend)
    encrypted = first.protect(b'fictional-token-for-testing')
    assert b'fictional-token' not in encrypted
    assert MacKeychainProtector(backend).unprotect(encrypted) == b'fictional-token-for-testing'
    assert first.protect(b'fictional-token-for-testing') != encrypted
    with pytest.raises(AIServiceError):
        first.unprotect(encrypted[:-1] + bytes([encrypted[-1] ^ 1]))
    with pytest.raises(AIServiceError, match='不是 Mac'):
        first.unprotect(b'windows-encrypted-credentials')
    with pytest.raises(AIServiceError, match='钥匙串'):
        MacKeychainProtector(MemoryKeychain()).unprotect(encrypted)


@pytest.mark.skipif(sys.platform != 'darwin', reason='Requires real macOS Keychain')
def test_real_mac_keychain_roundtrip():
    first = MacKeychainProtector()
    first._SERVICE = 'com.wangzhaolian.tests.' + uuid.uuid4().hex
    try:
        value = first.protect(b'fictional-test-data-only')
        second = MacKeychainProtector()
        second._SERVICE = first._SERVICE
        assert second.unprotect(value) == b'fictional-test-data-only'
    finally:
        first.backend.delete_password(first._SERVICE, first._ACCOUNT)


def test_mac_user_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(library, 'portable_home', lambda: None)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.delenv('ZHAOLIAN_PROFILE_HOME', raising=False)
    assert library.default_home() == tmp_path / 'Library/Application Support/ZhaolianProfile'
    assert chatgpt_auth.default_auth_home() == tmp_path / 'Library/Application Support/ZhaolianProfile/chatgpt'


def test_complete_folder_can_move_without_new_blank_library(tmp_path, monkeypatch):
    import shutil
    original = tmp_path / '原位置'
    app = original / '程序'
    app.mkdir(parents=True)
    data_home = original / '个人资料'
    identity = library.initialize_home(data_home)
    (original / 'portable-library.json').write_text(json.dumps({'library': '个人资料', 'library_id': identity}), encoding='utf-8')
    moved = tmp_path / 'Mac位置'
    shutil.copytree(original, moved)
    monkeypatch.setattr(library, 'resource_root', lambda: moved / '程序')
    monkeypatch.delenv('ZHAOLIAN_PROFILE_HOME', raising=False)
    assert library.default_home() == moved / '个人资料'
    assert library.initialize_home(library.default_home()) == identity
    (moved / '个人资料/private/library.local.json').write_text(json.dumps({'library_id': str(uuid.uuid4())}), encoding='utf-8')
    with pytest.raises(RuntimeError, match='标识不匹配'):
        library.default_home()


def test_missing_portable_data_is_not_replaced_with_empty_library(tmp_path, monkeypatch):
    (tmp_path / 'portable-library.json').write_text(json.dumps({'library': '个人资料', 'library_id': 'expected'}), encoding='utf-8')
    monkeypatch.setattr(library, 'resource_root', lambda: tmp_path)
    monkeypatch.delenv('ZHAOLIAN_PROFILE_HOME', raising=False)
    with pytest.raises(RuntimeError, match='完整复制'):
        library.default_home()
    assert not (tmp_path / '个人资料').exists()


def test_no_converter_keeps_original_and_explains_pdf_fallback(tmp_path, monkeypatch):
    source = tmp_path / 'original.docx'
    source.write_bytes(b'original-kept')
    monkeypatch.setattr(file_inputs.shutil, 'which', lambda name: None)
    monkeypatch.setattr(sys, 'platform', 'linux')
    with pytest.raises(ValueError, match='LibreOffice'):
        file_inputs._libreoffice_to_pdf(source, tmp_path / 'output.pdf')
    assert source.read_bytes() == b'original-kept'


@pytest.mark.skipif(sys.platform != 'darwin', reason='Requires macOS LibreOffice')
def test_real_macos_docx_conversion(tmp_path):
    from docx import Document
    source = tmp_path / '虚构文档.docx'
    document = Document()
    document.add_paragraph('Mac 迁移验收：这是一份虚构资料。')
    document.save(source)
    output = tmp_path / 'result.pdf'
    file_inputs._office_to_pdf(source, output)
    assert output.read_bytes().startswith(b'%PDF-')
    assert source.is_file()
