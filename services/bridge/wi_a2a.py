#!/usr/bin/env python3
# wi_a2a.py — A2A (Agent2Agent) protocol adapter for the worker IT-ops endpoint. Dependency-free:
# the caller injects run_skill(skill, meta) -> result | None; this module owns the Agent Card and the
# JSON-RPC message/send + tasks/get envelope (Linux-Foundation A2A shape). Co-located module —
# boot-stack cp's it next to worker-itops.py, same as ebg19p.py / knowledge.py.
import json
import time

A2A_SKILLS = {
    "monitor": {"id": "monitor", "name": "Device drift monitor", "description": "已核准 baseline 比對巡檢 + 安全退化告警", "tags": ["ops", "monitor"]},
    "fix":     {"id": "remediate", "name": "EBG19P remediation", "description": "EBG19P 確定性安全 remediation (ebg-wps/upnp/telnet…)", "tags": ["ops", "remediation"]},
    "cert":    {"id": "cert-scan", "name": "Certificate & crypto audit", "description": "憑證 / 弱加密盤點", "tags": ["ops", "cert"]},
    "cve":     {"id": "cve-scan", "name": "Fleet CVE scan", "description": "機隊 CVE 分級", "tags": ["security", "cve"]},
    "source":  {"id": "source-scan", "name": "SBOM / SAST source analysis", "description": "上游韌體原始碼 SBOM + SAST", "tags": ["security", "sast"]},
    "nuclei":  {"id": "nuclei-scan", "name": "Active vuln scan (nuclei)", "description": "nuclei-templates 主動掃 ASUS 裝置(projectdiscovery)", "tags": ["security", "nuclei", "dast"]},
  "backup":   {"id": "backup", "name": "Config backup / snapshot", "description": "EBG19P 設定版本化快照", "tags": ["governance", "backup"]},
  "firmware": {"id": "firmware-update", "name": "Firmware lifecycle", "description": "韌體版本 / 更新查核 · 分批上線", "tags": ["governance", "firmware"]},
  "rollback": {"id": "rollback", "name": "Restore known-good config", "description": "還原已知良好設定(需人核准)", "tags": ["governance", "rollback"]},
  "review":   {"id": "review", "name": "QA review (a/b outputs)", "description": "審查 worker-a/b 解法決策 → 綁定判決", "tags": ["governance", "review"]},
  "curate":   {"id": "curate", "name": "Skill curation (SkillOS)", "description": "審查技能庫 insert/update/delete:品質閘 + 抗膨脹 + BM25(arXiv 2605.06614)", "tags": ["governance", "skills", "curator"]},
}
A2A_KNOWLEDGE = {"id": "knowledge", "name": "Shared fleet knowledge", "description": "共享知識：核准 baseline / 安全鍵定義 / lessons / fleet 快照", "tags": ["knowledge", "context"]}


def build_agent_card(zone, caps, role, port):
    """A2A Agent Card — zone-scoped skill discovery. Pure; caller passes the live zone/caps/role/port."""
    skills = [A2A_SKILLS[c] for c in caps if c in A2A_SKILLS] + [A2A_KNOWLEDGE]
    return {
        "name": "nemofleet-worker-" + zone.lower(),
        "description": "NemoFleet " + (role or "") + " worker (zone " + zone + ")",
        "url": "http://127.0.0.1:%d/a2a" % port, "version": "1.0.0", "protocolVersion": "0.3.0",
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": False},
        "defaultInputModes": ["text"], "defaultOutputModes": ["text"],
        "provider": {"organization": "NemoFleet", "url": "http://127.0.0.1:%d/health" % port},
        "skills": skills,
    }


def message_send(params, run_skill):
    """A2A message/send → run the requested skill via the injected run_skill, return a Task object."""
    msg = params.get("message") or {}
    meta = msg.get("metadata") or {}
    text = " ".join(p.get("text", "") for p in (msg.get("parts") or []) if p.get("kind") == "text").strip()
    skill = meta.get("skill") or (text.split()[0] if text else "")
    tid = "task-" + str(int(time.time() * 1000))
    result = run_skill(skill, meta)
    if result is None:
        return {"id": tid, "kind": "task", "status": {"state": "rejected"},
                "artifacts": [{"artifactId": "error", "parts": [{"kind": "text", "text": "unknown skill '%s'; see agent-card skills" % skill}]}]}
    return {"id": tid, "contextId": msg.get("contextId") or tid, "kind": "task",
            "status": {"state": "completed"},
            "artifacts": [{"artifactId": "result", "parts": [{"kind": "text", "text": json.dumps(result, ensure_ascii=False)}]}]}


def handle_rpc(rpc, run_skill, last_task=None):
    """Dispatch a JSON-RPC 2.0 A2A request (message/send, tasks/get)."""
    rid = rpc.get("id")
    method = rpc.get("method")
    if method == "message/send":
        return {"jsonrpc": "2.0", "result": message_send(rpc.get("params") or {}, run_skill), "id": rid}
    if method == "tasks/get":
        return {"jsonrpc": "2.0", "result": (last_task or {"note": "no task"}), "id": rid}
    return {"jsonrpc": "2.0", "error": {"code": -32601, "message": "method not found: %s" % method}, "id": rid}
