"""Point d'entrée en ligne de commande : python -m ai_signal <commande>."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone

from dotenv import load_dotenv

from ai_signal.config import ROOT, load_settings


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def cmd_check_setup(args: argparse.Namespace) -> int:
    """Vérifie que l'installation est prête (Python, config, clé API)."""
    ok = True

    def line(status: bool, label: str, detail: str = "") -> None:
        nonlocal ok
        ok = ok and status
        mark = "OK " if status else "!! "
        print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))

    v = sys.version_info
    line(v >= (3, 11), "Python >= 3.11", f"version {v.major}.{v.minor}.{v.micro}")

    try:
        settings = load_settings()
        start, end = settings.window(_today_utc())
        line(True, "config/settings.yaml", f"fréquence={settings.frequency}, "
             f"fenêtre {start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} UTC")
    except Exception as e:  # noqa: BLE001 — on veut afficher n'importe quelle erreur de config
        line(False, "config/settings.yaml", str(e))
        return 1

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        line(False, "ANTHROPIC_API_KEY", "absente (fichier .env ou secret GitHub)")
    elif not key.startswith("sk-ant-"):
        line(False, "ANTHROPIC_API_KEY", "présente mais ne commence pas par 'sk-ant-'")
    else:
        line(True, "ANTHROPIC_API_KEY", f"présente (…{key[-4:]})")

    if args.ping and key:
        # Un tout petit appel à Haiku pour vérifier que la clé fonctionne (coût ≈ 0,0001 $).
        import anthropic

        try:
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model=settings.models.triage,
                max_tokens=64,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": "Reply with exactly: pong"}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            line(True, "Appel API Claude", f"{settings.models.triage} a répondu « {text} »")
        except anthropic.AuthenticationError:
            line(False, "Appel API Claude", "clé refusée (invalide ou révoquée)")
        except anthropic.PermissionDeniedError as e:
            line(False, "Appel API Claude", f"accès refusé : {e.message}")
        except anthropic.APIStatusError as e:
            line(False, "Appel API Claude", f"erreur {e.status_code} : {e.message}")
        except anthropic.APIConnectionError:
            line(False, "Appel API Claude", "impossible de joindre l'API (réseau)")

    print("\nTout est prêt." if ok else "\nIl reste des points à corriger (voir les lignes '!!').")
    return 0 if ok else 1


def _not_yet(phase: int):
    def _cmd(args: argparse.Namespace) -> int:
        print(f"Cette commande sera disponible à la phase {phase}.")
        return 2
    return _cmd


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ai_signal", description="AI Signal — agent de veille IA")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("check-setup", help="vérifie l'installation (Python, config, clé API)")
    s.add_argument("--ping", action="store_true", help="fait un mini appel à l'API pour tester la clé")
    s.set_defaults(func=cmd_check_setup)

    r = sub.add_parser("run", help="exécution complète")
    r.add_argument("--dry-run", action="store_true", help="ni email, ni publication")
    r.add_argument("--no-email", action="store_true", help="pas d'envoi d'email")
    r.add_argument("--date", type=date.fromisoformat, help="régénère une date passée (AAAA-MM-JJ)")
    r.set_defaults(func=_not_yet(4))

    sub.add_parser("collect-only", help="debug : affiche les éléments collectés").set_defaults(func=_not_yet(2))
    sub.add_parser("check-sources", help="teste tous les flux").set_defaults(func=_not_yet(2))
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    # Accents corrects dans la console Windows.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)
