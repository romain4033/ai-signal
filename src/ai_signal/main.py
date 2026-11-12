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


def _window(args: argparse.Namespace):
    """Fenêtre de collecte : celle de l'édition (--date), ou les N dernières heures (--hours)."""
    from datetime import timedelta

    settings = load_settings()
    if getattr(args, "hours", None):
        end = datetime.now(timezone.utc)
        return end - timedelta(hours=args.hours), end
    return settings.window(args.date or _today_utc())


def cmd_check_sources(args: argparse.Namespace) -> int:
    """Teste toutes les sources et affiche leur statut."""
    from ai_signal.collect import collect_all

    start, end = _window(args)
    print(f"Fenêtre : {start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} UTC\n")
    _, reports = collect_all(start, end)
    print(f"{'':3} {'Source':42} {'T':1} {'Méthode':15} {'Lus':>4} {'Fen.':>4}  {'Plus récent':16}  Détail")
    print("-" * 110)
    for r in sorted(reports, key=lambda r: (r.tier, r.name)):
        if not r.ok:
            mark = "!! "
        elif r.method == "web_search":
            mark = " - "
        elif r.total == 0:
            mark = " ? "
        else:
            mark = "OK "
        newest = f"{r.newest:%Y-%m-%d %H:%M}" if r.newest else ""
        print(f"{mark:3} {r.name[:42]:42} {r.tier:1} {r.method:15} {r.total:>4} {r.in_window:>4}  "
              f"{newest:16}  {r.error or f'{r.seconds}s'}")
    ok = sum(r.ok and r.total > 0 for r in reports)
    ko = [r.name for r in reports if not r.ok]
    print(f"\n{ok} sources OK, {len(ko)} en erreur, "
          f"{sum(r.method == 'web_search' for r in reports)} en recherche web.")
    print("Légende : OK = répond · ?  = répond mais vide · !! = erreur · - = pas de flux (web_search)")
    print("          Lus = éléments lus · Fen. = éléments gardés dans la fenêtre")
    return 0


def cmd_collect_only(args: argparse.Namespace) -> int:
    """Affiche les éléments collectés dans la fenêtre, par source."""
    from ai_signal.collect import collect_all

    start, end = _window(args)
    items, reports = collect_all(start, end)
    print(f"Fenêtre : {start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} UTC — {len(items)} éléments\n")
    by_source: dict[str, list] = {}
    for it in items:
        by_source.setdefault(it.source, []).append(it)
    for r in sorted(reports, key=lambda r: (r.tier, r.name)):
        its = by_source.get(r.name)
        if not its:
            continue
        print(f"── {r.name} (tier {r.tier}) — {len(its)}")
        for it in sorted(its, key=lambda i: i.published, reverse=True)[: args.limit]:
            extra = " · ".join(f"{k}={v}" for k, v in it.extra.items() if k != "hn_url")
            print(f"   {it.published:%m-%d %H:%M}  {it.title[:95]}" + (f"  [{extra}]" if extra else ""))
            print(f"                {it.url}")
        if len(its) > args.limit:
            print(f"   … et {len(its) - args.limit} autres")
        print()
    return 0


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

    for name, func, help_ in [
        ("check-sources", cmd_check_sources, "teste tous les flux et affiche leur statut"),
        ("collect-only", cmd_collect_only, "debug : affiche les éléments collectés"),
    ]:
        c = sub.add_parser(name, help=help_)
        c.add_argument("--date", type=date.fromisoformat, help="fenêtre de l'édition de cette date")
        c.add_argument("--hours", type=int, help="fenêtre glissante : les N dernières heures")
        if name == "collect-only":
            c.add_argument("--limit", type=int, default=8, help="éléments affichés par source")
        c.set_defaults(func=func)
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    # Accents corrects dans la console Windows.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)
