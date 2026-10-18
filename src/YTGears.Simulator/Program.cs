using System;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace YTGears.Simulator
{
    internal static class Program
    {
        private static int Main(string[] args)
        {
            Console.OutputEncoding = Encoding.UTF8;
            if (args.Length > 2 || (args.Length == 2 && args[1] != "--json") || (args.Length > 0 && args[0] == "--help"))
            {
                Console.WriteLine("Запуск: dotnet run --project src/YTGears.Simulator -- [examples/baseline.json] [--json]");
                return args.Length > 0 && args[0] == "--help" ? 0 : 2;
            }
            try
            {
                string path = args.Length > 0 ? args[0] : "examples/baseline.json";
                var options = new JsonSerializerOptions
                {
                    PropertyNameCaseInsensitive = true, WriteIndented = true,
                    UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow
                };
                options.Converters.Add(new JsonStringEnumConverter<Core.DonationRule>(allowIntegerValues: false));
                options.Converters.Add(new JsonStringEnumConverter<Core.RoundPhase>(allowIntegerValues: false));
                var scenario = JsonSerializer.Deserialize<Scenario>(File.ReadAllText(path), options)
                    ?? throw new ArgumentException("Empty scenario");
                var report = ScenarioRunner.Run(scenario);
                if (args.Length == 2) Console.WriteLine(JsonSerializer.Serialize(report, options));
                else
                {
                    var result = report.Result;
                    Console.WriteLine("ИМИТАЦИЯ: YouTube и реальные платежи не подключены.");
                    Console.WriteLine($"Предварительные правила: Mview=1+{scenario.Policy.ViewerSlope}×max(0,V−1), донаты={scenario.Policy.DonationRule}, срок={scenario.Policy.DonationDurationSeconds?.ToString() ?? "до конца раунда"}, предел ×{scenario.Policy.MaximumMultiplier}.");
                    foreach (var line in report.EventLog) Console.WriteLine(line);
                    Console.WriteLine($"Время до логического контакта: {result.ActualSecondsToImpact:F6} с (база {result.BaseSeconds} с).");
                    Console.WriteLine($"Ударов: {report.ImpactCount}; донатов: {result.DonationCount}; сумма: {result.DonationTotalUsd:G29} USD.");
                    Console.WriteLine($"Уникальные зрители: недоступно. Уникальные ускорившие: недоступно. Наблюдаемый пик онлайна: {result.ObservedPeakConcurrentViewers?.ToString() ?? "недоступно"}.");
                    Console.WriteLine($"Максимальный множитель: ×{result.MaxAppliedMultiplier:F6}; предел достигнут: {result.SpeedCapReached}; пропуски данных: {result.ViewerDataGapObserved}.");
                    var teeth = report.ToothCandidate;
                    Console.WriteLine($"Геометрия НЕ утверждена: кандидат {teeth.DriverTeeth}:{teeth.DrivenTeeth}, валов {teeth.ShaftCount}, колёс {teeth.WheelCount}, ошибка времени {teeth.RelativeTimeError:P6}.");
                }
                return 0;
            }
            catch (Exception ex) when (ex is ArgumentException || ex is IOException || ex is JsonException || ex is OverflowException)
            { Console.Error.WriteLine($"Ошибка сценария: {ex.Message}"); return 2; }
        }
    }
}
