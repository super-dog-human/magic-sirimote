"""One explicitly requested, run-bound owner-mode repair; no sensor writes."""
import os
from pathlib import Path
from owner_entry import execute_if_requested
import native_app_identity,local_attestation
PLAN={'controllerState': {'generic-presensor-intent-0979491c453d98cb0e773192218db598-0ee209580eb54d48833dc7fc38d2cc9d.json': {'mode': 416, 'sha256': 'e3abbe8b9b30b88db5cbecd810046f4c1396f6fdd1b9f4284b1f07a8140ceac3'}, 'generic-presensor-result-0979491c453d98cb0e773192218db598-0ee209580eb54d48833dc7fc38d2cc9d.json': {'mode': 416, 'sha256': '52d63f1d78822cbce3a011c4cc9695a93da3e9c67b9ad6d1dd60b0db3fd0fe80'}, 'receiver-launch-intent.json': {'mode': 416, 'sha256': 'b9cd486b5fe9e5f48fbdc00e0ffcd04180823f4abcbf3472a5fc78fa2689783d'}, 'supervisor.lock': {'mode': 384, 'sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'}}, 'receiverControllerOwned': {'controller-start.json': {'mode': 432, 'sha256': '1432354d0743f71fb7327b37c72bf1e767e7fcdb80ca44ab7d487b45f526a67e'}, 'request.json': {'mode': 432, 'sha256': 'b4e2f7fabc2a285866060ad24473d5609074ea09e8a4063129a5b82fa4c022c9'}}, 'receiverJournal': {'borrowed-0979491c453d98cb0e773192218db598-01.json': {'mode': 416, 'sha256': 'c42a8cfc3b3d85fc1b2624ea274e8eb289f31552a584c6ca8381d3a73df94371'}, 'borrowed-0979491c453d98cb0e773192218db598-02.json': {'mode': 416, 'sha256': '364f77988abef071b9cb7674eb30887a29de732f3ff6e451e9e41a7dfff3464d'}}, 'receiverOwned': {'feature-control.lock': {'mode': 384, 'sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'}, 'receiver-result-0979491c453d98cb0e773192218db598.json': {'mode': 416, 'sha256': 'cc8c5e2eed5cef73a9b038708f1e5ddc3071bad3ddcf092c116ab80290c696a2'}, 'receiver-start-0979491c453d98cb0e773192218db598.json': {'mode': 416, 'sha256': '0c1bdca90d2a55e6329b7102677d3b7ac7cd88c9b2e4ce4b0a5b95cf8c475ea6'}}, 'run': '0979491c453d98cb0e773192218db598'}
A='org.codex.siriremote.autocoord20261029v'
B='org.codex.siriremote.hidgattrouterb20261029u'
ROOT=Path('/media/developer/apps/usr/palm/applications')
def maybe_repair(role):
 if role not in ('controller','receiver'):raise ValueError('invalid role')
 own=A if role=='controller' else B;other=B if role=='controller' else A
 def guard():
  return (native_app_identity.verify_self() is True and local_attestation.candidate_pids(ROOT/own)==[os.getpid()] and local_attestation.candidate_pids(ROOT/other)==[])
 result=execute_if_requested(role,PLAN,controller_state=ROOT/A/'state',receiver_state=ROOT/B/'state',journal_state=ROOT/B/'state'/'borrowed-active',guard=guard)
 if result is None:return False
 if result.get('status')!='repaired':raise RuntimeError('owner repair unconfirmed')
 return True
