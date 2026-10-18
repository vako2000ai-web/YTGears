using System;
using System.Collections.Generic;

namespace YTGears.Core
{
    public sealed class Transmission
    {
        public RoundParameters Parameters { get; }
        public double TotalRatio => Parameters.TargetSeconds / RoundParameters.FirstPeriodSeconds;
        public double StageRatio { get; }
        public IReadOnlyList<double> PeriodsSeconds { get; }

        public Transmission(RoundParameters parameters)
        {
            Parameters = parameters ?? throw new ArgumentNullException(nameof(parameters));
            StageRatio = Math.Pow(TotalRatio, 1.0 / (parameters.GearCount - 1));
            var periods = new double[parameters.GearCount];
            for (int i = 0; i < periods.Length; i++)
                periods[i] = RoundParameters.FirstPeriodSeconds * Math.Pow(TotalRatio, (double)i / (periods.Length - 1));
            periods[0] = RoundParameters.FirstPeriodSeconds;
            periods[periods.Length - 1] = parameters.TargetSeconds;
            PeriodsSeconds = Array.AsReadOnly(periods);
        }

        public double AngleDegrees(int index, double mechanismSeconds, double initialAngleDegrees = 0)
        {
            if (index < 0 || index >= Parameters.GearCount) throw new ArgumentOutOfRangeException(nameof(index));
            Guard.Finite(mechanismSeconds, nameof(mechanismSeconds), 0, Parameters.TargetSeconds);
            Guard.Finite(initialAngleDegrees, nameof(initialAngleDegrees), -1e12, 1e12);
            return initialAngleDegrees + (index % 2 == 0 ? 1 : -1) * 360 * (mechanismSeconds / PeriodsSeconds[index]);
        }

        /// <summary>Candidate compound train, not geometry approval. Each stage has two wheels.</summary>
        public ToothCandidate ApproximateTeeth(int minTeeth = 12, int maxTeeth = 120)
        {
            if (minTeeth < 4 || maxTeeth < minTeeth || maxTeeth > 4096) throw new ArgumentOutOfRangeException(nameof(maxTeeth));
            int driver = minTeeth, driven = minTeeth;
            double bestError = double.MaxValue;
            for (int a = minTeeth; a <= maxTeeth; a++)
            {
                int b = (int)Math.Max(minTeeth, Math.Min(maxTeeth, Math.Round(a * StageRatio)));
                double error = Math.Abs(Math.Log((double)b / a) - Math.Log(StageRatio));
                if (error < bestError) { bestError = error; driver = a; driven = b; }
            }
            double actualPeriod = RoundParameters.FirstPeriodSeconds * Math.Pow((double)driven / driver, Parameters.GearCount - 1);
            return new ToothCandidate(driver, driven, Parameters.GearCount, actualPeriod,
                (actualPeriod - Parameters.TargetSeconds) / Parameters.TargetSeconds);
        }
    }

    public sealed class ToothCandidate
    {
        public int DriverTeeth { get; }
        public int DrivenTeeth { get; }
        public int ShaftCount { get; }
        public int WheelCount => 2 * (ShaftCount - 1);
        public double ActualLastPeriodSeconds { get; }
        public double RelativeTimeError { get; }
        public bool GeometryApproved => false;
        internal ToothCandidate(int driver, int driven, int shafts, double period, double error)
        { DriverTeeth = driver; DrivenTeeth = driven; ShaftCount = shafts; ActualLastPeriodSeconds = period; RelativeTimeError = error; }
    }
}
