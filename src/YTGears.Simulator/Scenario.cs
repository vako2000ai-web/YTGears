using System;
using System.Collections.Generic;
using System.Linq;
using YTGears.Core;

namespace YTGears.Simulator
{
    public sealed class Scenario
    {
        public string RoundId { get; set; } = "simulation";
        public int GearCount { get; set; } = 8;
        public double TargetSeconds { get; set; } = 1800;
        public double StepSeconds { get; set; } = 1;
        public PolicyInput Policy { get; set; } = new PolicyInput();
        public List<ScenarioEvent> Events { get; set; } = new List<ScenarioEvent>();
    }

    public sealed class PolicyInput
    {
        public double ViewerSlope { get; set; } = 0.1;
        public double ViewerTransitionSeconds { get; set; } = 2;
        public double ViewerTimeoutSeconds { get; set; } = 30;
        public double MaximumMultiplier { get; set; } = 64;
        public DonationRule DonationRule { get; set; } = DonationRule.SingleBoost;
        public double? DonationDurationSeconds { get; set; }
        public SpeedPolicy Build() => new SpeedPolicy(ViewerSlope, ViewerTransitionSeconds, ViewerTimeoutSeconds,
            MaximumMultiplier, DonationRule, DonationDurationSeconds);
    }

    public sealed class ScenarioEvent
    {
        public double AtSeconds { get; set; }
        public string Type { get; set; } = "";
        public int? Viewers { get; set; }
        public string? RoundId { get; set; }
        public string Provider { get; set; } = "simulator";
        public string Id { get; set; } = "";
        public decimal AmountUsd { get; set; }
        public string Currency { get; set; } = "USD";
        public bool Confirmed { get; set; } = true;
        public Donation ToDonation(string defaultRoundId) => new Donation(RoundId ?? defaultRoundId, Provider, Id, AmountUsd, Currency, Confirmed);
    }

    public sealed class SimulationReport
    {
        public string Mode => "SIMULATION - experimental policies, no real YouTube or payments";
        public Scenario Configuration { get; }
        public ToothCandidate ToothCandidate { get; }
        public RoundResult Result { get; }
        public int ImpactCount { get; }
        public RoundPhase FinalPhase { get; }
        public IReadOnlyList<string> EventLog { get; }

        internal SimulationReport(Scenario scenario, MechanismRound round, List<string> log)
        {
            Configuration = scenario; ToothCandidate = round.Transmission.ApproximateTeeth();
            Result = round.Result ?? throw new InvalidOperationException("Round has not finished");
            ImpactCount = round.ImpactCount; FinalPhase = round.Phase; EventLog = log.AsReadOnly();
        }
    }

    public static class ScenarioRunner
    {
        public static SimulationReport Run(Scenario scenario)
        {
            if (scenario == null || scenario.Policy == null || scenario.Events == null) throw new ArgumentException("Scenario, policy and events required");
            if (!double.IsFinite(scenario.StepSeconds) || scenario.StepSeconds < 0.01 || scenario.StepSeconds > 1e12)
                throw new ArgumentException("StepSeconds must be finite and in [0.01, 1e12]");
            // Bound execution work explicitly; no accidental trillion-step CLI runs.
            if (scenario.TargetSeconds / scenario.StepSeconds > 10_000_000)
                throw new ArgumentException("Scenario exceeds 10 million steps; increase StepSeconds");
            var round = new MechanismRound(scenario.RoundId, new RoundParameters(scenario.GearCount, scenario.TargetSeconds), scenario.Policy.Build());
            foreach (var e in scenario.Events)
            {
                if (e == null || !double.IsFinite(e.AtSeconds) || e.AtSeconds < 0 || e.AtSeconds > 1e12)
                    throw new ArgumentException("Event time must be finite and in [0, 1e12]");
                if (e.Type == "donation") _ = e.ToDonation(scenario.RoundId);
                else if (e.Type != "viewers" || e.Viewers < 0) throw new ArgumentException("Expected viewers or donation event, with nonnegative viewers/null");
            }
            // Stable sort: events with identical timestamps use JSON array order.
            var events = scenario.Events.OrderBy(e => e.AtSeconds).ToArray();
            var log = new List<string>();
            foreach (var e in events)
            {
                while (round.Phase == RoundPhase.Running && round.ElapsedSeconds < e.AtSeconds)
                    round.Advance(Math.Min(scenario.StepSeconds, e.AtSeconds - round.ElapsedSeconds));
                if (e.Type == "donation")
                    log.Add(FormattableString.Invariant($"{e.AtSeconds:F6}s donation {e.Provider}/{e.Id}: {round.ReceiveDonation(e.ToDonation(scenario.RoundId))}"));
                else
                    log.Add(FormattableString.Invariant($"{e.AtSeconds:F6}s viewers={e.Viewers?.ToString() ?? "unavailable"}: {(round.ObserveViewers(e.Viewers) ? "applied" : "round closed")}"));
            }
            while (round.Phase == RoundPhase.Running) round.Advance(scenario.StepSeconds);
            // Mock presentation acknowledgement only. No animation is rendered here.
            round.BeginDestruction(); round.CompleteDestruction();
            return new SimulationReport(scenario, round, log);
        }
    }
}
