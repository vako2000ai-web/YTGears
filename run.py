"""One entry point: 3D by default, explicit --simulate for offline JSON playback."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="YTGears / Gear & Porcelain — Python 3D")
    parser.add_argument("--gears", type=int, default=8, help="число расчётных валов")
    parser.add_argument("--seconds", type=float, default=1800, help="базовое время до контакта")
    parser.add_argument("--demo", action="store_true", help="короткий раунд: N=5, T=180, 51 имитируемый зритель")
    parser.add_argument("--simulate", metavar="JSON", help="проиграть автономный сценарий без графики")
    parser.add_argument("--json", action="store_true", help="JSON-отчёт для --simulate")
    parser.add_argument("--offscreen", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--capture", metavar="PNG", help=argparse.SUPPRESS)
    parser.add_argument("--capture-impact", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.simulate:
            from ytgears.scenario import json_report, load_scenario, run_scenario
            path = Path(args.simulate)
            report = run_scenario(load_scenario(path if path.is_absolute() else ROOT / path))
            if args.json: print(json_report(report))
            else:
                result = report["result"]
                print(report["mode"])
                for line in report["event_log"]: print(line)
                print(f"Контакт: {result['actual_seconds_to_impact']:.6f} с; ударов: {report['impact_count']}; "
                      f"донатов: {result['donation_count']}; USD: {result['donation_total_usd']}")
                print("Уникальные зрители: недоступно; пик онлайна:", result["observed_peak_concurrent_viewers"])
            return 0
        from ytgears.scene import GearPorcelainApp
        app = GearPorcelainApp(args)
        app.run()
        return 0
    except ImportError as exc:
        print(f"Не установлен компонент: {exc}. Запустите start.bat или pip install -r requirements.txt", file=sys.stderr)
        return 2
    except (ValueError, OSError, ArithmeticError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
