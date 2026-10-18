using System;

namespace YTGears.Core
{
    public enum RoundPhase { Running, Impacted, Destruction, Results }
    public enum DonationStatus { Accepted, Duplicate, ConflictingDuplicate, Unconfirmed, UnsupportedCurrency, WrongRound, RoundClosed }

    public sealed class Donation
    {
        public string RoundId { get; }
        public string Provider { get; }
        public string EventId { get; }
        public decimal Amount { get; }
        public string Currency { get; }
        public bool Confirmed { get; }

        public Donation(string roundId, string provider, string eventId, decimal amount, string currency = "USD", bool confirmed = true)
        {
            if (string.IsNullOrWhiteSpace(roundId)) throw new ArgumentException("Round ID required", nameof(roundId));
            if (string.IsNullOrWhiteSpace(provider)) throw new ArgumentException("Provider required", nameof(provider));
            if (string.IsNullOrWhiteSpace(eventId)) throw new ArgumentException("Event ID required", nameof(eventId));
            if (amount <= 0) throw new ArgumentOutOfRangeException(nameof(amount));
            if (string.IsNullOrWhiteSpace(currency)) throw new ArgumentException("Currency required", nameof(currency));
            RoundId = roundId; Provider = provider; EventId = eventId; Amount = amount;
            Currency = currency.ToUpperInvariant(); Confirmed = confirmed;
        }
    }

    /// <summary>Frozen at logical contact. null metrics mean unavailable, never zero people.</summary>
    public sealed class RoundResult
    {
        public string RoundId { get; }
        public double ActualSecondsToImpact { get; }
        public double BaseSeconds { get; }
        public double SavedSeconds => BaseSeconds - ActualSecondsToImpact;
        public int? UniqueViewers => null;
        public int? UniqueAcceleratingViewers => null;
        public string ViewerMetricStatus => "Unavailable: concurrent samples cannot identify unique viewers";
        public int? ObservedPeakConcurrentViewers { get; }
        public double MaxViewerMultiplier { get; }
        public double MaxAppliedMultiplier { get; }
        public bool SpeedCapReached { get; }
        public int DonationCount { get; }
        public decimal DonationTotalUsd { get; }
        public bool ViewerSourceAvailableAtImpact { get; }
        public bool ViewerDataGapObserved { get; }

        internal RoundResult(string id, double elapsed, double baseline, int? peak, double maxViewer,
            double maxSpeed, bool capReached, int count, decimal total, bool viewerAvailable, bool dataGap)
        {
            RoundId = id; ActualSecondsToImpact = elapsed; BaseSeconds = baseline;
            ObservedPeakConcurrentViewers = peak; MaxViewerMultiplier = maxViewer;
            MaxAppliedMultiplier = maxSpeed; SpeedCapReached = capReached;
            DonationCount = count; DonationTotalUsd = total;
            ViewerSourceAvailableAtImpact = viewerAvailable; ViewerDataGapObserved = dataGap;
        }
    }
}
