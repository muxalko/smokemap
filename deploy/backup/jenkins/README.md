# Jenkins completed-backup export

The publisher accepts an existing paired capture with an owner-private
`backup.json`, `database.dump`, and `media.tar`. The receipt must identify the
source directory and confirm both archives were taken during the same writer
quiescence window and that the original services recovered. This script
validates lengths and SHA-256 digests from that receipt before publication.

The Jenkins operator must provision `~/.local/state/smokemap-offvm-export`
with mode 0700. Run the publisher as the same owner, with an absolute source
directory and a new run ID. For example:

```sh
python3 deploy/backup/jenkins/publish_backup.py --source /absolute/completed-capture --run-id development-20261109-example
```

The private output contains the paired archives and a receiver manifest.
The export remains plaintext on Jenkins and is readable only by the owner.
Linux no-replace rename makes completed output visible atomically, and the
publisher reports the source receipt hash, source capture time and export
manifest hash. Keep the original capture and reconcile an uncertain publication
before creating a replacement. A publication receipt alone does not prove an
off-VM copy or an application restore.

Run fixture tests on Jenkins with:

```sh
PYTHONPATH=deploy/backup/jenkins python3 -B deploy/backup/jenkins/tests/test_publish_backup.py -v
```
