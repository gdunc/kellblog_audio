from pathlib import Path

from kellblog_audio.publish import backup_qa_reports, restore_qa_reports


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.upload_calls: list[str] = []

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.objects[key] = Path(filename).read_bytes()
        self.upload_calls.append(key)

    def download_file(self, bucket, key, filename):
        Path(filename).write_bytes(self.objects[key])

    def list_objects_v2(self, Bucket, Prefix):
        contents = [{"Key": key} for key in sorted(self.objects) if key.startswith(Prefix)]
        return {"Contents": contents}


def test_backup_and_restore_qa_reports_round_trip_json_only(tmp_path, monkeypatch):
    qa_dir = tmp_path / "qa"
    qa_dir.mkdir()
    (qa_dir / "pass.qa.json").write_text('{"passed": true}', encoding="utf-8")
    (qa_dir / "pass.txt").write_text("transcript should stay local", encoding="utf-8")

    dest = tmp_path / "restored-qa"
    dest.mkdir()
    client = FakeS3Client()
    monkeypatch.setattr("kellblog_audio.publish.get_s3_client", lambda: client)
    monkeypatch.setattr("kellblog_audio.publish.QA_TRANSCRIPTS_DIR", qa_dir)

    key = backup_qa_reports(key="backup/qa-reports-test.zip")
    assert key == "backup/qa-reports-test.zip"
    assert client.upload_calls == [key]

    monkeypatch.setattr("kellblog_audio.publish.QA_TRANSCRIPTS_DIR", dest)
    assert restore_qa_reports(key=key) is True
    assert (dest / "pass.qa.json").read_text(encoding="utf-8") == '{"passed": true}'
    assert not (dest / "pass.txt").exists()
