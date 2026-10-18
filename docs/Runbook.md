# Запуск и подключение ядра

## Сборка и проверки

Из корня репозитория, .NET SDK 10.0. Сторонние пакеты не требуются; `NuGet.Config` очищает внешние источники. `global.json` допускает установленный feature band SDK 10.0.

```powershell
dotnet build YTGears.sln -c Release --disable-build-servers -m:1
dotnet run --project tests/YTGears.Checks -c Release --no-build
dotnet run --project src/YTGears.Simulator -c Release --no-build -- examples/baseline.json
dotnet run --project src/YTGears.Simulator -c Release --no-build -- examples/interactive.json
dotnet run --project src/YTGears.Simulator -c Release --no-build -- examples/experimental-stacking.json
```

Машинный JSON-отчёт с конфигурацией, геометрическим кандидатом, журналом и итогами:

```powershell
dotnet run --project src/YTGears.Simulator -c Release --no-build -- examples/interactive.json --json
```

При запрете записи в пользовательский каталог .NET можно указать локальный:

```powershell
$env:DOTNET_CLI_HOME = Join-Path $PWD '.dotnet-home'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
```

Код выхода проверок 0 означает успех, 1 — провал. CLI возвращает 2 при неверных аргументах, JSON или сценарии. Нужен именно запуск исполняемых проверок, а не `dotnet test`. Сборка с одним узлом и без серверов также работает в ограниченной среде; Unity для неё не требуется.

## Параметры JSON

| Поле | По умолчанию | Значение |
| --- | --- | --- |
| `roundId` | simulation | Непустой идентификатор раунда |
| `gearCount` | 8 | N, целое 2..4096; именно расчётных периодов |
| `targetSeconds` | 1800 | T, конечное 12 < T ≤ 10^12 с |
| `stepSeconds` | 1 | Максимальный шаг проигрывателя 0.01..10^12 с; события не округляются к шагу |
| `policy.viewerSlope` | 0.1 | Предварительное линейное ускорение от дополнительных зрителей, 0..10^6 |
| `policy.viewerTransitionSeconds` | 2 | Линейное сглаживание; 0 отключает, максимум 10^12 с |
| `policy.viewerTimeoutSeconds` | 30 | TTL последнего отсчёта, 0.001..10^12 с |
| `policy.maximumMultiplier` | 64 | Предварительный общий предел, 2..10^6 |
| `policy.donationRule` | SingleBoost | `SingleBoost` либо явно экспериментальный `WholeDollarsDoubling` |
| `policy.donationDurationSeconds` | null | null: до конца раунда; иначе срок каждого принятого платежа, 0.001..10^12 с |
| `events` | [] | Список зрительских/донатных входов |

Неизвестные JSON-поля отвергаются, чтобы опечатка не подменила настройку значением по умолчанию. Для защиты CLI от случайно огромного числа шагов требуется T/step ≤ 10 миллионов.

`SingleBoost`: активные USD суммируются; при сумме ≥1 донатный множитель равен 2. Последующие платежи увеличивают статистику, но не множитель. `WholeDollarsDoubling`: множитель равен `2^floor(active USD)` до общего ограничения. Это два проверяемых экспериментальных варианта. Ни один не утверждён как правило реального эфира.

При ограниченном сроке каждый платёж удаляется из активной суммы по собственной границе; общий счётчик и полученная сумма не уменьшаются. Дробные суммы используют decimal. Неподтверждённые, не-USD, чужие раунды и дубликаты не входят в итоговую сумму. Переполнение decimal отвергается до изменения состояния.

В `baseline.json` TTL намеренно увеличен до 3600 с, чтобы один имитируемый отсчёт «1 зритель» оставался свежим весь раунд. В реальном адаптере нужны повторные запросы, а не такой обход свежести.

## Входные события

```json
{ "atSeconds": 10, "type": "viewers", "viewers": 11 }
```

`viewers: null` означает недоступный источник, `0` — достоверно полученный нулевой отсчёт. При отсутствии источника используется базовая скорость; уникальная аудитория остаётся неизвестной. Повторный одинаковый отсчёт продлевает TTL, но не перезапускает сглаживание.

```json
{ "atSeconds": 20, "type": "donation", "provider": "simulator", "id": "payment-1", "amountUsd": 1, "currency": "USD", "confirmed": true }
```

`provider` по умолчанию `simulator`; `currency` — USD; `confirmed` — true; `roundId` события — идентификатор сценария. Непустой ID обязателен. Суммы записываются JSON-числом с точкой. События сортируются по времени, равные времена сохраняют порядок массива. Перед каждым событием интегрируется предыдущий интервал. Если ровно в этот момент достигнуто T, контакт имеет приоритет и донат получает `RoundClosed`.

Истёкшие эффекты удаляются на своей границе до новых входов. Ядро не перематывает время и не имеет сетевых timestamps: для реального адаптера именно хост должен задать последовательное время получения. Симулятор выводит запланированные поздние события как отклонённые; они не увеличивают время/статистику завершённого раунда.

## API для будущего движка

```csharp
var round = new MechanismRound("round-001", new RoundParameters(8, 1800), new SpeedPolicy());
round.ObserveViewers(1);
// Для каждого входа: сначала Advance до его времени, затем ObserveViewers/ReceiveDonation.
// В каждом кадре передаётся реальный монотонный dt, без timeScale и без умножения на M.
bool contactedNow = round.Advance(deltaSeconds);
double firstAngle = round.Transmission.AngleDegrees(0, round.MechanismSeconds);
double progress = round.Progress;
if (contactedNow)
{
    // Ровно один запуск клипа контакта/разрушения и звука; Result уже заморожен.
    round.BeginDestruction();
}
// По завершении клипа на отдельных часах презентации:
// if (round.CompleteDestruction()) ShowResults(round.Result);
```

Библиотека `src/YTGears.Core/bin/Release/netstandard2.1/YTGears.Core.dll` не ссылается на графический движок. Подключение в Editor/IL2CPP ещё не проверялось; переносимость по целевой платформе не следует считать доказанной только успешной CLI-сборкой.

Хост должен хранить порядок входов, не вызывать ядро с разных потоков, не запускать новую анимацию по постоянному условию `Progress == 1`, сохранять конфигурацию/результат и проверять подтверждения платежей. N, T и политика неизменяемы внутри одного раунда. Текущая реализация не сохраняет раунд на диск и не восстанавливает дедупликацию после перезапуска.

`ActualSecondsToImpact` сейчас означает рассчитанное реальное время до логического контакта. В JSON `UniqueViewers` и `UniqueAcceleratingViewers` равны null, а `ViewerMetricStatus` объясняет причину. `ObservedPeakConcurrentViewers` может быть 0, числом или null. Метки доступности и пропусков обязательны для честного итогового интерфейса.
