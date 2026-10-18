using System;

namespace YTGears.Core
{
    internal static class Guard
    {
        public static double Finite(double value, string name, double min, double max = double.MaxValue)
        {
            if (double.IsNaN(value) || double.IsInfinity(value) || value < min || value > max)
                throw new ArgumentOutOfRangeException(name);
            return value;
        }
    }

    public sealed class RoundParameters
    {
        public const double FirstPeriodSeconds = 12;
        public int GearCount { get; }
        public double TargetSeconds { get; }

        public RoundParameters(int gearCount = 8, double targetSeconds = 1800)
        {
            // Explicit resource/numeric bounds of this implementation, not product requirements.
            if (gearCount < 2 || gearCount > 4096) throw new ArgumentOutOfRangeException(nameof(gearCount));
            Guard.Finite(targetSeconds, nameof(targetSeconds), FirstPeriodSeconds, 1e12);
            if (targetSeconds == FirstPeriodSeconds) throw new ArgumentOutOfRangeException(nameof(targetSeconds));
            GearCount = gearCount;
            TargetSeconds = targetSeconds;
        }
    }

    public enum DonationRule
    {
        // PRELIMINARY: one non-stacking x2 boost once active USD reaches 1.
        SingleBoost,
        // PRELIMINARY opt-in only: 2^floor(active USD).
        WholeDollarsDoubling
    }

    /// <summary>Experimental policies. Immutable for the lifetime of a round.</summary>
    public sealed class SpeedPolicy
    {
        public double ViewerSlope { get; }
        public double ViewerTransitionSeconds { get; }
        public double ViewerTimeoutSeconds { get; }
        public double MaximumMultiplier { get; }
        public DonationRule DonationRule { get; }
        public double? DonationDurationSeconds { get; }

        public SpeedPolicy(double viewerSlope = 0.1, double viewerTransitionSeconds = 2,
            double viewerTimeoutSeconds = 30, double maximumMultiplier = 64,
            DonationRule donationRule = DonationRule.SingleBoost, double? donationDurationSeconds = null)
        {
            ViewerSlope = Guard.Finite(viewerSlope, nameof(viewerSlope), 0, 1e6);
            ViewerTransitionSeconds = Guard.Finite(viewerTransitionSeconds, nameof(viewerTransitionSeconds), 0, 1e12);
            ViewerTimeoutSeconds = Guard.Finite(viewerTimeoutSeconds, nameof(viewerTimeoutSeconds), 0.001, 1e12);
            MaximumMultiplier = Guard.Finite(maximumMultiplier, nameof(maximumMultiplier), 2, 1e6);
            if (!Enum.IsDefined(typeof(DonationRule), donationRule)) throw new ArgumentOutOfRangeException(nameof(donationRule));
            DonationRule = donationRule;
            DonationDurationSeconds = donationDurationSeconds.HasValue
                ? Guard.Finite(donationDurationSeconds.Value, nameof(donationDurationSeconds), 0.001, 1e12) : (double?)null;
        }

        public double ViewerMultiplier(int viewers) => Math.Min(MaximumMultiplier, 1 + ViewerSlope * Math.Max(0L, (long)viewers - 1));

        public double DonationMultiplier(decimal activeUsd)
        {
            if (activeUsd < 1) return 1;
            if (DonationRule == DonationRule.SingleBoost) return 2;
            // Clamp the exponent before exponentiation, including huge valid decimal payments.
            return Math.Pow(2, Math.Min((double)decimal.Floor(activeUsd), Math.Log(MaximumMultiplier, 2)));
        }
    }
}
