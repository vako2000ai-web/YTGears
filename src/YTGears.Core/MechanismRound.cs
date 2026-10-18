using System;
using System.Collections.Generic;

namespace YTGears.Core
{
    /// <summary>
    /// Single-threaded deterministic domain object. Advance to event time BEFORE applying the event.
    /// Time is supplied by the host's monotonic clock; no Unity, network or wall-clock dependencies.
    /// </summary>
    public sealed class MechanismRound
    {
        private sealed class ActiveDonation
        {
            public decimal Usd { get; }
            public double Expires { get; }
            public ActiveDonation(decimal usd, double expires) { Usd = usd; Expires = expires; }
        }

        private readonly Dictionary<(string, string), Donation> receipts = new Dictionary<(string, string), Donation>();
        private readonly List<ActiveDonation> activeDonations = new List<ActiveDonation>();
        private decimal activeUsd;
        private decimal totalUsd;
        private double? viewerExpires;
        private double viewerValue = 1;
        private double viewerTarget = 1;
        private double rampRemaining;
        private double maxViewer = 1;
        private double maxApplied = 1;
        private bool capReached;
        private int? peakViewers;
        private bool dataGap;

        public string RoundId { get; }
        public Transmission Transmission { get; }
        public SpeedPolicy Policy { get; }
        public RoundPhase Phase { get; private set; } = RoundPhase.Running;
        public double MechanismSeconds { get; private set; }
        public double ElapsedSeconds { get; private set; }
        public double Progress => MechanismSeconds / Transmission.Parameters.TargetSeconds;
        public RoundResult? Result { get; private set; }
        public int ImpactCount { get; private set; }
        public bool ViewerSourceAvailable => viewerExpires.HasValue;
        public double ViewerMultiplier => viewerValue;
        public double DonationMultiplier => Policy.DonationMultiplier(activeUsd);
        public double AppliedMultiplier => Math.Min(Policy.MaximumMultiplier, viewerValue * DonationMultiplier);

        public MechanismRound(string roundId, RoundParameters? parameters = null, SpeedPolicy? policy = null)
        {
            if (string.IsNullOrWhiteSpace(roundId)) throw new ArgumentException("Round ID required", nameof(roundId));
            RoundId = roundId;
            Transmission = new Transmission(parameters ?? new RoundParameters());
            Policy = policy ?? new SpeedPolicy();
        }

        /// <summary>null explicitly marks a missing/disconnected source; zero is a real observed zero.</summary>
        public bool ObserveViewers(int? concurrentViewers)
        {
            if (concurrentViewers < 0) throw new ArgumentOutOfRangeException(nameof(concurrentViewers));
            if (Phase != RoundPhase.Running) return false;
            if (concurrentViewers.HasValue)
            {
                peakViewers = Math.Max(peakViewers ?? 0, concurrentViewers.Value);
                viewerExpires = ElapsedSeconds + Policy.ViewerTimeoutSeconds;
                SetViewerTarget(Policy.ViewerMultiplier(concurrentViewers.Value));
            }
            else
            {
                viewerExpires = null; dataGap = true; SetViewerTarget(1);
            }
            TrackSpeed();
            return true;
        }

        public DonationStatus ReceiveDonation(Donation donation)
        {
            if (donation == null) throw new ArgumentNullException(nameof(donation));
            if (donation.RoundId != RoundId) return DonationStatus.WrongRound;
            if (Phase != RoundPhase.Running) return DonationStatus.RoundClosed;
            if (!donation.Confirmed) return DonationStatus.Unconfirmed;
            if (donation.Currency != "USD") return DonationStatus.UnsupportedCurrency;
            var key = (donation.Provider, donation.EventId);
            if (receipts.TryGetValue(key, out var previous))
                return previous.Amount == donation.Amount && previous.Currency == donation.Currency
                    ? DonationStatus.Duplicate : DonationStatus.ConflictingDuplicate;
            // Check decimal overflow before any mutation, preserving atomic acceptance.
            decimal nextTotal = checked(totalUsd + donation.Amount);
            decimal nextActive = checked(activeUsd + donation.Amount);
            var effect = new ActiveDonation(donation.Amount, Policy.DonationDurationSeconds.HasValue
                ? ElapsedSeconds + Policy.DonationDurationSeconds.Value : double.PositiveInfinity);
            receipts.Add(key, donation); activeDonations.Add(effect);
            totalUsd = nextTotal; activeUsd = nextActive;
            TrackSpeed();
            return DonationStatus.Accepted;
        }

        private void SetViewerTarget(double target)
        {
            // Repeated identical samples refresh freshness without restarting a ramp.
            if (target == viewerTarget) return;
            viewerTarget = target; rampRemaining = Policy.ViewerTransitionSeconds;
            if (rampRemaining == 0) viewerValue = target;
        }

        private void ExpireInputs()
        {
            if (viewerExpires.HasValue && viewerExpires.Value <= ElapsedSeconds)
            { viewerExpires = null; dataGap = true; SetViewerTarget(1); }
            for (int i = activeDonations.Count - 1; i >= 0; i--)
                if (activeDonations[i].Expires <= ElapsedSeconds)
                { activeUsd -= activeDonations[i].Usd; activeDonations.RemoveAt(i); }
        }

        private void TrackSpeed()
        {
            maxViewer = Math.Max(maxViewer, viewerValue);
            maxApplied = Math.Max(maxApplied, AppliedMultiplier);
            capReached |= viewerValue * DonationMultiplier >= Policy.MaximumMultiplier;
        }

        // Exact integral of min(cap, (viewerValue + slope*t) * donation) on a linear segment.
        private double Integrate(double seconds, double slope, double donation)
        {
            double start = viewerValue * donation;
            double rate = slope * donation;
            double end = start + rate * seconds;
            double cap = Policy.MaximumMultiplier;
            if (Math.Max(start, end) <= cap) return (start + end) * 0.5 * seconds;
            if (Math.Min(start, end) >= cap) return cap * seconds;
            double crossing = (cap - start) / rate;
            return rate > 0
                ? (start + cap) * 0.5 * crossing + cap * (seconds - crossing)
                : cap * crossing + (cap + end) * 0.5 * (seconds - crossing);
        }

        /// <returns>true only on the call that reaches logical contact; results are already frozen.</returns>
        public bool Advance(double deltaSeconds)
        {
            Guard.Finite(deltaSeconds, nameof(deltaSeconds), 0, 1e12);
            if (Phase != RoundPhase.Running || deltaSeconds == 0) return false;
            double remainingStep = deltaSeconds;
            while (remainingStep > 0)
            {
                ExpireInputs();
                double segment = remainingStep;
                if (viewerExpires.HasValue) segment = Math.Min(segment, viewerExpires.Value - ElapsedSeconds);
                foreach (var effect in activeDonations) segment = Math.Min(segment, effect.Expires - ElapsedSeconds);
                if (rampRemaining > 0) segment = Math.Min(segment, rampRemaining);
                if (!ViewerSourceAvailable) dataGap = true;
                double slope = rampRemaining > 0 ? (viewerTarget - viewerValue) / rampRemaining : 0;
                double donation = DonationMultiplier;
                double distance = Transmission.Parameters.TargetSeconds - MechanismSeconds;
                double integrated = Integrate(segment, slope, donation);
                bool impact = integrated >= distance;
                double consumed = segment;
                if (impact)
                {
                    // Monotonic integral: solve within this segment, independent of render step size.
                    double lo = 0, hi = segment;
                    for (int i = 0; i < 64; i++)
                    {
                        double mid = lo + (hi - lo) * 0.5;
                        if (Integrate(mid, slope, donation) < distance) lo = mid; else hi = mid;
                    }
                    consumed = hi;
                }
                TrackSpeed();
                viewerValue += slope * consumed;
                rampRemaining = Math.Max(0, rampRemaining - consumed);
                if (rampRemaining == 0) viewerValue = viewerTarget;
                ElapsedSeconds += consumed;
                MechanismSeconds = impact ? Transmission.Parameters.TargetSeconds : MechanismSeconds + integrated;
                TrackSpeed();
                if (impact)
                {
                    ImpactCount = 1; Phase = RoundPhase.Impacted;
                    Result = new RoundResult(RoundId, ElapsedSeconds, Transmission.Parameters.TargetSeconds,
                        peakViewers, maxViewer, maxApplied, capReached, receipts.Count, totalUsd,
                        ViewerSourceAvailable, dataGap || !peakViewers.HasValue);
                    return true;
                }
                // At an input boundary, public state must already reflect expirations.
                // Contact above takes precedence over inputs delivered at the same instant.
                ExpireInputs();
                remainingStep = Math.Max(0, remainingStep - segment);
            }
            return false;
        }

        public bool BeginDestruction()
        {
            if (Phase != RoundPhase.Impacted) return false;
            Phase = RoundPhase.Destruction; return true;
        }

        public bool CompleteDestruction()
        {
            if (Phase != RoundPhase.Destruction) return false;
            Phase = RoundPhase.Results; return true;
        }
    }
}
