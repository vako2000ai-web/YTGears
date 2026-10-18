using System;
using System.Collections.Generic;
using YTGears.Core;
using YTGears.Simulator;

internal static class Program
{
    private static int passed, failed;
    private static void Check(string name, Action test)
    {
        try { test(); passed++; Console.WriteLine($"PASS {name}"); }
        catch (Exception ex) { failed++; Console.Error.WriteLine($"FAIL {name}: {ex}"); }
    }
    private static void Assert(bool value, string message = "Assertion failed")
    { if (!value) throw new Exception(message); }
    private static void Near(double expected, double actual, double tolerance = 1e-8)
    { Assert(Math.Abs(expected - actual) <= tolerance, $"Expected {expected:R}, actual {actual:R}"); }
    private static void Throws<T>(Action action) where T : Exception
    { try { action(); } catch (T) { return; } throw new Exception($"Expected {typeof(T).Name}"); }
    private static MechanismRound Round(double target = 1800, SpeedPolicy? policy = null) => new MechanismRound("r", new RoundParameters(8, target), policy);
    private static Donation Pay(string id = "p", decimal usd = 1, bool confirmed = true, string currency = "USD", string round = "r", string provider = "sim")
        => new Donation(round, provider, id, usd, currency, confirmed);
    private static void Finish(MechanismRound round, double step = 10000)
    { while (round.Phase == RoundPhase.Running) round.Advance(step); }

    private static int Main()
    {
        Check("baseline: several N/T, last revolution and exact contact", () =>
        {
            foreach (int n in new[] { 2, 8, 32 })
            foreach (double t in new[] { 13.0, 1800, 7200 })
            {
                var r = new MechanismRound("r", new RoundParameters(n, t));
                r.ObserveViewers(1); Finish(r, 0.37);
                Near(t, r.ElapsedSeconds, 2e-7); Near(t, r.MechanismSeconds);
                Near(12, r.Transmission.PeriodsSeconds[0]); Near(t, r.Transmission.PeriodsSeconds[n - 1]);
                Near(360, Math.Abs(r.Transmission.AngleDegrees(n - 1, r.MechanismSeconds)));
                Assert(r.ImpactCount == 1 && r.Progress == 1 && r.Result!.DonationCount == 0);
            }
        });
        Check("transmission: q and alternating continuous angles", () =>
        {
            var r = Round(); var tx = r.Transmission;
            Near(150, tx.TotalRatio); Near(Math.Pow(150, 1.0 / 7), tx.StageRatio);
            for (int k = 0; k < 7; k++) Near(tx.StageRatio, tx.PeriodsSeconds[k + 1] / tx.PeriodsSeconds[k]);
            r.Advance(6); Near(180, tx.AngleDegrees(0, r.MechanismSeconds));
            double before = tx.AngleDegrees(1, r.MechanismSeconds, 20);
            r.ReceiveDonation(Pay()); r.ObserveViewers(100); r.Advance(0);
            Near(before, tx.AngleDegrees(1, r.MechanismSeconds, 20));
            Assert(tx.AngleDegrees(1, r.MechanismSeconds) < 0);
        });
        Check("constant USD 1 boost halves actual time", () =>
        {
            var r = Round(); Assert(r.ReceiveDonation(Pay()) == DonationStatus.Accepted);
            Near(2, r.AppliedMultiplier); Finish(r); Near(900, r.ElapsedSeconds);
        });
        Check("mid-round boost integrates old and new speed", () =>
        {
            var r = Round(); r.Advance(300); r.ReceiveDonation(Pay()); Finish(r);
            Near(1050, r.ElapsedSeconds); Near(1800, r.MechanismSeconds);
        });
        Check("direct viewer changes affect all gears with no angle reset", () =>
        {
            var r = Round(1800, new SpeedPolicy(viewerSlope: 1, viewerTransitionSeconds: 0, viewerTimeoutSeconds: 10000));
            r.ObserveViewers(1); r.Advance(100); r.ObserveViewers(4); r.Advance(100);
            Near(500, r.MechanismSeconds); r.ObserveViewers(2); Finish(r); Near(850, r.ElapsedSeconds);
        });
        Check("donation replay, conflicting payload and provider namespaces", () =>
        {
            var r = Round(); r.ReceiveDonation(Pay());
            Assert(r.ReceiveDonation(Pay()) == DonationStatus.Duplicate);
            Assert(r.ReceiveDonation(Pay(usd: 9)) == DonationStatus.ConflictingDuplicate);
            Assert(r.ReceiveDonation(Pay(provider: "other")) == DonationStatus.Accepted);
            Finish(r); Assert(r.Result!.DonationCount == 2 && r.Result.DonationTotalUsd == 2);
            Near(900, r.ElapsedSeconds); // Default SingleBoost explicitly does not stack.
        });
        Check("pending can later confirm; non-USD/wrong round do not count", () =>
        {
            var r = Round();
            Assert(r.ReceiveDonation(Pay(confirmed: false)) == DonationStatus.Unconfirmed);
            Assert(r.ReceiveDonation(Pay(currency: "EUR")) == DonationStatus.UnsupportedCurrency);
            Assert(r.ReceiveDonation(Pay(round: "other")) == DonationStatus.WrongRound);
            Assert(r.ReceiveDonation(Pay()) == DonationStatus.Accepted);
            Finish(r); Assert(r.Result!.DonationCount == 1 && r.Result.DonationTotalUsd == 1);
        });
        Check("fractions use decimal; experimental accumulation is opt-in", () =>
        {
            var r = Round(policy: new SpeedPolicy(donationRule: DonationRule.WholeDollarsDoubling));
            r.ReceiveDonation(Pay("a", 0.4m)); Near(1, r.DonationMultiplier);
            r.ReceiveDonation(Pay("b", 0.6m)); Near(2, r.DonationMultiplier);
            r.ReceiveDonation(Pay("c", 1m)); Near(4, r.DonationMultiplier);
            Finish(r); Assert(r.Result!.DonationTotalUsd == 2 && r.Result.DonationCount == 3); Near(450, r.ElapsedSeconds);
        });
        Check("cap clamps huge exponent without numeric overflow", () =>
        {
            var r = Round(policy: new SpeedPolicy(maximumMultiplier: 7, donationRule: DonationRule.WholeDollarsDoubling));
            r.ReceiveDonation(Pay(usd: decimal.MaxValue)); Near(7, r.AppliedMultiplier);
            r.ObserveViewers(int.MaxValue); Finish(r); Near(1800.0 / 7, r.ElapsedSeconds);
            Assert(r.Result!.SpeedCapReached && r.Result.DonationTotalUsd == decimal.MaxValue);
        });
        Check("overflow rejection is atomic", () =>
        {
            var r = Round(); r.ReceiveDonation(Pay("max", decimal.MaxValue));
            Throws<OverflowException>(() => r.ReceiveDonation(Pay("overflow", 1)));
            Finish(r); Assert(r.Result!.DonationCount == 1 && r.Result.DonationTotalUsd == decimal.MaxValue);
        });
        Check("timed donations expire inside a coarse step, totals remain", () =>
        {
            var r = Round(100, new SpeedPolicy(donationDurationSeconds: 10));
            r.ReceiveDonation(Pay()); Finish(r); Near(90, r.ElapsedSeconds);
            Assert(r.Result!.DonationCount == 1 && r.Result.DonationTotalUsd == 1);
        });
        Check("expiring fractional payments use individual windows", () =>
        {
            var r = Round(100, new SpeedPolicy(donationDurationSeconds: 10));
            r.ReceiveDonation(Pay("a", 0.4m)); r.Advance(5); r.ReceiveDonation(Pay("b", 0.6m));
            r.Advance(5); Near(15, r.MechanismSeconds); Near(1, r.DonationMultiplier);
            r.Advance(1); Near(16, r.MechanismSeconds); Near(1, r.DonationMultiplier);
            Finish(r); Near(95, r.ElapsedSeconds); Assert(r.Result!.DonationTotalUsd == 1);
        });
        Check("viewer freshness timeout and smooth fallback have exact integral", () =>
        {
            var r = Round(100, new SpeedPolicy(viewerTransitionSeconds: 2, viewerTimeoutSeconds: 10));
            r.ObserveViewers(11); r.Advance(10); Near(19, r.MechanismSeconds); Near(2, r.ViewerMultiplier);
            r.Advance(1); Near(1.5, r.ViewerMultiplier); r.Advance(1); Near(22, r.MechanismSeconds);
            Finish(r); Near(90, r.ElapsedSeconds); Assert(r.Result!.ViewerDataGapObserved);
            Assert(!r.Result.ViewerSourceAvailableAtImpact && r.Result.ObservedPeakConcurrentViewers == 11);
        });
        Check("new event exactly at expiry sees expired contributions removed", () =>
        {
            var r = Round(100, new SpeedPolicy(donationDurationSeconds: 10, donationRule: DonationRule.WholeDollarsDoubling));
            r.ReceiveDonation(Pay("a", 1)); r.Advance(10); Near(1, r.DonationMultiplier);
            r.ReceiveDonation(Pay("b", 1)); Near(2, r.DonationMultiplier);
            Finish(r); Near(80, r.ElapsedSeconds); Near(2, r.Result!.MaxAppliedMultiplier);
        });
        Check("identical viewer samples refresh TTL without restarting smoothing", () =>
        {
            var r = Round(100, new SpeedPolicy(viewerTransitionSeconds: 2, viewerTimeoutSeconds: 10));
            r.ObserveViewers(11); r.Advance(1); r.ObserveViewers(11); r.Advance(1); Near(2, r.ViewerMultiplier);
            r.Advance(8.5); Assert(r.ViewerSourceAvailable); r.Advance(1); Assert(!r.ViewerSourceAvailable);
        });
        Check("disconnect/recovery; zero and missing are different metrics", () =>
        {
            var r = Round(100); r.ObserveViewers(0); r.Advance(1); r.ObserveViewers(null);
            r.Advance(1); r.ObserveViewers(5); Finish(r);
            Assert(r.Result!.UniqueViewers == null && r.Result.UniqueAcceleratingViewers == null);
            Assert(r.Result.ObservedPeakConcurrentViewers == 5 && r.Result.ViewerDataGapObserved);
            var absent = Round(100); Finish(absent); Assert(absent.Result!.ObservedPeakConcurrentViewers == null);
            var zero = Round(100); zero.ObserveViewers(0); Finish(zero); Assert(zero.Result!.ObservedPeakConcurrentViewers == 0);
            var gap = Round(100); gap.Advance(1); gap.ObserveViewers(1); Finish(gap); Assert(gap.Result!.ViewerDataGapObserved);
        });
        Check("speed cap crossing during viewer ramp is integrated", () =>
        {
            var r = Round(100, new SpeedPolicy(viewerSlope: 1, viewerTransitionSeconds: 2, viewerTimeoutSeconds: 1000, maximumMultiplier: 3));
            r.ReceiveDonation(Pay()); r.ObserveViewers(3); r.Advance(2);
            Near(5.75, r.MechanismSeconds); Finish(r); Near(2 + 94.25 / 3, r.ElapsedSeconds);
        });
        Check("one strike, frozen results, explicit destruction and results", () =>
        {
            var r = Round(100); Assert(!r.CompleteDestruction()); Assert(!r.BeginDestruction());
            Assert(r.Advance(1000)); var frozen = r.Result;
            for (int i = 0; i < 100; i++) Assert(!r.Advance(10));
            Assert(r.ReceiveDonation(Pay()) == DonationStatus.RoundClosed && !r.ObserveViewers(99));
            Assert(r.ImpactCount == 1 && ReferenceEquals(frozen, r.Result)); Near(100, r.ElapsedSeconds);
            Assert(r.BeginDestruction() && !r.BeginDestruction());
            Assert(r.CompleteDestruction() && !r.CompleteDestruction()); Assert(r.Phase == RoundPhase.Results);
            Assert(frozen!.DonationCount == 0); Near(100, frozen.ActualSecondsToImpact);
        });
        Check("parameters of a next round cannot change a running round", () =>
        {
            var r = Round(100); r.Advance(10); var next = new RoundParameters(3, 200);
            Near(100, r.Transmission.Parameters.TargetSeconds); Assert(next.GearCount == 3);
            Finish(r); Near(100, r.ElapsedSeconds);
        });
        Check("integer teeth report physical wheel count and timing mismatch", () =>
        {
            var tx = new Transmission(new RoundParameters()); var teeth = tx.ApproximateTeeth();
            Assert(!teeth.GeometryApproved && teeth.WheelCount == 14 && teeth.ShaftCount == 8);
            Near(teeth.ActualLastPeriodSeconds / 1800 - 1, teeth.RelativeTimeError);
            Assert(Math.Abs(teeth.RelativeTimeError) > 1e-8);
            var exact = new Transmission(new RoundParameters(3, 48)).ApproximateTeeth();
            Near(0, exact.RelativeTimeError); Assert(exact.DrivenTeeth == 2 * exact.DriverTeeth);
            var impossible = new Transmission(new RoundParameters(2, 1800)).ApproximateTeeth();
            Assert(Math.Abs(impossible.RelativeTimeError) > 0.9);
        });
        Check("reject malformed parameters and events", () =>
        {
            foreach (double bad in new[] { double.NaN, double.PositiveInfinity, 0, -1, 12, 1e13 }) Throws<ArgumentOutOfRangeException>(() => new RoundParameters(8, bad));
            Throws<ArgumentOutOfRangeException>(() => new RoundParameters(1));
            Throws<ArgumentOutOfRangeException>(() => new RoundParameters(4097));
            Throws<ArgumentOutOfRangeException>(() => new SpeedPolicy(maximumMultiplier: 1));
            Throws<ArgumentOutOfRangeException>(() => new SpeedPolicy(donationDurationSeconds: 0));
            Throws<ArgumentOutOfRangeException>(() => new SpeedPolicy(donationRule: (DonationRule)99));
            Throws<ArgumentOutOfRangeException>(() => Round().Advance(double.NaN));
            Throws<ArgumentOutOfRangeException>(() => Round().Advance(-1));
            Throws<ArgumentOutOfRangeException>(() => Round().ObserveViewers(-1));
            Throws<ArgumentOutOfRangeException>(() => Pay(usd: 0));
            Throws<ArgumentException>(() => Pay(id: ""));
        });
        Check("simulator processes exact event times and rejects donation at contact", () =>
        {
            var scenario = new Scenario { TargetSeconds = 100, StepSeconds = 17, RoundId = "r" };
            scenario.Events.Add(new ScenarioEvent { AtSeconds = 20, Type = "donation", Id = "one", AmountUsd = 1 });
            scenario.Events.Add(new ScenarioEvent { AtSeconds = 60, Type = "donation", Id = "late", AmountUsd = 10 });
            var report = ScenarioRunner.Run(scenario);
            Near(60, report.Result.ActualSecondsToImpact); Assert(report.Result.DonationCount == 1);
            Assert(report.EventLog[1].EndsWith("RoundClosed") && report.ImpactCount == 1 && report.FinalPhase == RoundPhase.Results);
            Throws<ArgumentException>(() => ScenarioRunner.Run(new Scenario { StepSeconds = 0 }));
            var bad = new Scenario(); bad.Events.Add(new ScenarioEvent { AtSeconds = -1, Type = "viewers" });
            Throws<ArgumentException>(() => ScenarioRunner.Run(bad));
        });
        Check("seeded replay: coarse and fine steps agree across ramps, caps, expiry and replays", () =>
        {
            for (int seed = 0; seed < 30; seed++)
            {
                var random = new Random(seed);
                var scenario = new Scenario { TargetSeconds = 300, StepSeconds = 1000, RoundId = "r",
                    Policy = new PolicyInput { ViewerTimeoutSeconds = 7, ViewerTransitionSeconds = 3,
                        MaximumMultiplier = 5, DonationDurationSeconds = 9, DonationRule = DonationRule.WholeDollarsDoubling } };
                for (int i = 0; i < 20; i++)
                {
                    scenario.Events.Add(new ScenarioEvent { AtSeconds = i * 4 + 0.13, Type = "viewers", Viewers = i % 5 == 0 ? null : random.Next(0, 70) });
                    scenario.Events.Add(new ScenarioEvent { AtSeconds = i * 4 + 0.7, Type = "donation", Id = (i / 2).ToString(), AmountUsd = 0.5m });
                }
                var coarse = ScenarioRunner.Run(scenario); scenario.StepSeconds = 0.07;
                var fine = ScenarioRunner.Run(scenario);
                Near(coarse.Result.ActualSecondsToImpact, fine.Result.ActualSecondsToImpact, 2e-8);
                Near(coarse.Result.MaxAppliedMultiplier, fine.Result.MaxAppliedMultiplier);
                Assert(coarse.Result.DonationTotalUsd == fine.Result.DonationTotalUsd);
                Assert(coarse.ImpactCount == 1 && fine.ImpactCount == 1);
            }
        });
        Console.WriteLine($"Checks: {passed} passed, {failed} failed");
        return failed == 0 ? 0 : 1;
    }
}
