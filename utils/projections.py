"""
Portfolio projection utilities using Monte Carlo simulation and other methods.
Provides return projections, risk analysis, and financial planning calculations.
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ProjectionResults:
    """Results from portfolio projection calculations"""
    final_values: np.ndarray  # Array of final portfolio values
    percentiles: Dict[int, float]  # Key percentiles (5, 25, 50, 75, 95)
    expected_return: float  # Expected annualized return
    probability_of_loss: float  # Probability of negative returns
    var_95: float  # Value at Risk at 95% confidence
    cvar_95: float  # Conditional Value at Risk
    projection_years: int
    simulations: int
    initial_value: float

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'percentiles': self.percentiles,
            'expected_return': self.expected_return,
            'probability_of_loss': self.probability_of_loss,
            'var_95': self.var_95,
            'cvar_95': self.cvar_95,
            'projection_years': self.projection_years,
            'simulations': self.simulations,
            'initial_value': self.initial_value
        }


@dataclass
class ScenarioResult:
    """Results for a single scenario"""
    name: str
    description: str
    expected_return: float
    expected_volatility: float
    projected_value: float
    probability_of_loss: float


class PortfolioProjector:
    """Portfolio projection using various methods with dynamic market parameters"""

    def __init__(self, market_data_service=None):
        """
        Initialize projector with market data service

        Args:
            market_data_service: Service for fetching market parameters (optional)
        """
        self.market_data_service = market_data_service
        self._market_params_cache = None
        self._cache_timestamp = None
        self._cache_timeout = timedelta(hours=1)
        logger.info("Initialized PortfolioProjector")

    def _get_market_parameters(self) -> Dict[str, float]:
        """Get market parameters from service or cache"""
        if self.market_data_service is None:
            # Return sensible defaults if no service provided
            return {
                'expected_return': 0.12,
                'volatility': 0.22,
                'risk_free_rate': 0.0625,
                'inflation_rate': 0.046
            }

        # Check cache
        if (self._market_params_cache and self._cache_timestamp and
                datetime.now() - self._cache_timestamp < self._cache_timeout):
            return self._market_params_cache

        # Fetch fresh parameters
        try:
            self._market_params_cache = self.market_data_service.get_market_parameters()
            self._cache_timestamp = datetime.now()
            return self._market_params_cache
        except Exception as e:
            logger.error(f"Error fetching market parameters: {e}")
            # Return defaults if service fails
            return {
                'expected_return': 0.12,
                'volatility': 0.22,
                'risk_free_rate': 0.0625,
                'inflation_rate': 0.046
            }

    def monte_carlo_projection(
            self,
            current_value: float,
            historical_returns: Optional[pd.Series] = None,
            expected_return: Optional[float] = None,
            volatility: Optional[float] = None,
            years: int = 5,
            simulations: int = 10000,
            method: str = 'parametric',
            random_seed: Optional[int] = None
    ) -> ProjectionResults:
        """
        Run Monte Carlo simulation for portfolio projections

        Args:
            current_value: Current portfolio value
            historical_returns: Historical returns series (for historical method)
            expected_return: Expected annual return (for parametric method)
            volatility: Annual volatility (for parametric method)
            years: Number of years to project
            simulations: Number of Monte Carlo simulations
            method: 'historical' or 'parametric'
            random_seed: Random seed for reproducibility

        Returns:
            ProjectionResults object with simulation results
        """
        if random_seed is not None:
            np.random.seed(random_seed)

        logger.info(f"Running {method} Monte Carlo with {simulations} simulations for {years} years")

        # Validate inputs
        if current_value <= 0:
            raise ValueError("Current portfolio value must be positive")

        # Get market parameters if not provided
        if method == 'parametric' and (expected_return is None or volatility is None):
            market_params = self._get_market_parameters()
            expected_return = expected_return or market_params['expected_return']
            volatility = volatility or market_params['volatility']
            logger.info(f"Using market parameters: return={expected_return:.2%}, volatility={volatility:.2%}")

        if method == 'historical' and historical_returns is None:
            raise ValueError("Historical returns required for historical method")

        # Run appropriate simulation
        if method == 'historical':
            final_values = self._historical_monte_carlo(
                current_value, historical_returns, years, simulations
            )
        else:  # parametric
            final_values = self._parametric_monte_carlo(
                current_value, expected_return, volatility, years, simulations
            )

        # Calculate results
        returns = (final_values / current_value) ** (1/years) - 1

        # Calculate percentiles
        percentiles = {
            5: np.percentile(final_values, 5),
            25: np.percentile(final_values, 25),
            50: np.percentile(final_values, 50),
            75: np.percentile(final_values, 75),
            95: np.percentile(final_values, 95)
        }

        # Calculate risk metrics
        probability_of_loss = np.sum(final_values < current_value) / simulations
        var_95 = percentiles[5]  # 5th percentile for 95% VaR

        # Calculate CVaR (expected value in worst 5% of cases)
        worst_cases = final_values[final_values <= var_95]
        cvar_95 = np.mean(worst_cases) if len(worst_cases) > 0 else var_95

        results = ProjectionResults(
            final_values=final_values,
            percentiles=percentiles,
            expected_return=np.mean(returns),
            probability_of_loss=probability_of_loss,
            var_95=var_95,
            cvar_95=cvar_95,
            projection_years=years,
            simulations=simulations,
            initial_value=current_value
        )

        logger.info(f"Projection complete. Expected return: {results.expected_return:.2%}")

        return results

    @staticmethod
    def _parametric_monte_carlo(
            current_value: float,
            annual_return: float,
            annual_vol: float,
            years: int,
            simulations: int
    ) -> np.ndarray:
        """
        Parametric Monte Carlo using normal distribution

        Assumes log-normal distribution of returns
        """
        # Generate random returns using geometric Brownian motion
        dt = 1  # Annual time step

        # Adjust for continuous compounding
        drift = annual_return - 0.5 * annual_vol ** 2

        # Generate random shocks
        random_shocks = np.random.normal(0, 1, size=(simulations, years))

        # Calculate returns for each year
        returns = np.exp(drift * dt + annual_vol * np.sqrt(dt) * random_shocks)

        # Calculate final values
        final_values = current_value * np.prod(returns, axis=1)

        return final_values

    @staticmethod
    def _historical_monte_carlo(
            current_value: float,
            historical_returns: pd.Series,
            years: int,
            simulations: int
    ) -> np.ndarray:
        """
        Historical Monte Carlo using bootstrapped returns

        Randomly samples from historical returns with replacement
        """
        # Clean historical returns
        returns_clean = historical_returns.dropna()

        if len(returns_clean) < 30:
            logger.warning(f"Limited historical data: only {len(returns_clean)} returns available")

        # Convert to annual returns if daily
        if len(returns_clean) > 250:  # Likely daily data
            # Group into annual returns
            annual_returns = (1 + returns_clean).resample('Y').prod() - 1
            returns_to_sample = annual_returns.values
        else:
            returns_to_sample = returns_clean.values

        # Bootstrap returns
        final_values = np.zeros(simulations)

        for i in range(simulations):
            # Randomly sample returns with replacement
            sampled_returns = np.random.choice(returns_to_sample, size=years, replace=True)

            # Calculate final value
            final_values[i] = current_value * np.prod(1 + sampled_returns)

        return final_values

    def scenario_analysis(
            self,
            current_value: float,
            years: int = 5,
            custom_scenarios: Optional[Dict[str, Dict[str, float]]] = None
    ) -> List[ScenarioResult]:
        """
        Run projections under different market scenarios

        Args:
            current_value: Current portfolio value
            years: Number of years to project
            custom_scenarios: Optional custom scenarios to use

        Returns:
            List of ScenarioResult objects
        """
        # Get scenarios from market data service if available
        if custom_scenarios is None and self.market_data_service:
            try:
                scenarios = self.market_data_service.get_scenario_parameters()
            except Exception as e:
                logger.error(f"Error getting scenarios from market service: {e}")
                scenarios = self._get_default_scenarios()
        else:
            scenarios = custom_scenarios or self._get_default_scenarios()

        results = []

        for scenario_key, scenario in scenarios.items():
            # Run simplified projection for each scenario
            expected_value = current_value * (1 + scenario['return']) ** years

            # Quick Monte Carlo for probability of loss
            try:
                mc_result = self.monte_carlo_projection(
                    current_value=current_value,
                    expected_return=scenario['return'],
                    volatility=scenario['volatility'],
                    years=years,
                    simulations=1000,  # Fewer simulations for scenarios
                    method='parametric'
                )
                prob_of_loss = mc_result.probability_of_loss
            except Exception as e:
                logger.error(f"Error in scenario Monte Carlo: {e}")
                # Simple calculation if Monte Carlo fails
                prob_of_loss = 0.5 if scenario['return'] < 0 else 0.2

            results.append(ScenarioResult(
                name=scenario['name'],
                description=scenario['description'],
                expected_return=scenario['return'],
                expected_volatility=scenario['volatility'],
                projected_value=expected_value,
                probability_of_loss=prob_of_loss
            ))

        return results

    def _get_default_scenarios(self) -> Dict[str, Dict[str, float]]:
        """Get default scenarios based on market parameters"""
        market_params = self._get_market_parameters()
        base_return = market_params['expected_return']
        base_volatility = market_params['volatility']

        return {
            'bull': {
                'name': 'Bull Market',
                'description': 'Strong economic growth, positive reforms',
                'return': base_return * 1.5,
                'volatility': base_volatility * 0.8
            },
            'base': {
                'name': 'Base Case',
                'description': 'Normal market conditions based on historical average',
                'return': base_return,
                'volatility': base_volatility
            },
            'bear': {
                'name': 'Bear Market',
                'description': 'Economic slowdown, global headwinds',
                'return': base_return * 0.3,
                'volatility': base_volatility * 1.5
            },
            'crash': {
                'name': 'Market Crash',
                'description': 'Severe recession, systemic crisis',
                'return': -0.20,
                'volatility': base_volatility * 2.5
            }
        }

    def calculate_fire_number(
            self,
            annual_expenses: float,
            current_age: int,
            retirement_age: int,
            life_expectancy: int = 90,
            inflation_rate: Optional[float] = None,
            withdrawal_rate: float = 0.03  # 3% SWR for India
    ) -> Dict[str, float]:
        """
        Calculate Financial Independence Retire Early (FIRE) projections

        Args:
            annual_expenses: Current annual expenses
            current_age: Current age
            retirement_age: Target retirement age
            life_expectancy: Expected life span
            inflation_rate: Expected inflation rate (uses market data if not provided)
            withdrawal_rate: Safe withdrawal rate (default: 3% for India)

        Returns:
            Dictionary with FIRE calculations
        """
        try:
            # Get inflation rate from market data if not provided
            if inflation_rate is None:
                market_params = self._get_market_parameters()
                inflation_rate = market_params.get('inflation_rate', 0.05)

            years_to_retirement = retirement_age - current_age

            if years_to_retirement <= 0:
                raise ValueError("Retirement age must be greater than current age")

            # Adjust expenses for inflation at retirement
            future_annual_expenses = annual_expenses * (1 + inflation_rate) ** years_to_retirement

            # FIRE number (based on withdrawal rate)
            fire_number = future_annual_expenses / withdrawal_rate

            # Years in retirement
            retirement_years = life_expectancy - retirement_age

            if retirement_years <= 0:
                retirement_years = 30  # Default assumption

            # Get expected market return from parameters
            market_params = self._get_market_parameters()
            expected_return = market_params.get('expected_return', 0.12)

            # Total needed (considering inflation during retirement)
            total_retirement_needs = self._calculate_retirement_needs(
                future_annual_expenses,
                retirement_years,
                inflation_rate,
                expected_return
            )

            return {
                'fire_number': float(fire_number),
                'annual_expenses_today': float(annual_expenses),
                'annual_expenses_at_retirement': float(future_annual_expenses),
                'years_to_retirement': int(years_to_retirement),
                'retirement_years': int(retirement_years),
                'total_retirement_needs': float(total_retirement_needs),
                'withdrawal_rate': float(withdrawal_rate)
            }

        except Exception as e:
            logger.error(f"Error in FIRE calculation: {e}")
            raise ValueError(f"FIRE calculation failed: {str(e)}")

    def calculate_required_savings(
            self,
            current_value: float,
            target_value: float,
            years: int,
            expected_return: Optional[float] = None
    ) -> Dict[str, float]:
        """
        Calculate required monthly savings to reach target

        Args:
            current_value: Current portfolio value
            target_value: Target portfolio value
            years: Years to reach target
            expected_return: Expected annual return (uses market data if not provided)

        Returns:
            Dictionary with savings calculations
        """
        try:
            # Validate inputs
            if current_value < 0 or target_value <= 0 or years <= 0:
                raise ValueError("All values must be positive")

            # Get expected return from market data if not provided
            if expected_return is None:
                market_params = self._get_market_parameters()
                expected_return = market_params.get('expected_return', 0.12)

            months = years * 12
            monthly_return = expected_return / 12

            # Future value of current portfolio
            fv_current = current_value * (1 + expected_return) ** years

            # Remaining amount needed
            remaining = target_value - fv_current

            if remaining <= 0:
                return {
                    'monthly_savings_needed': 0.0,
                    'total_savings_needed': 0.0,
                    'current_value': float(current_value),
                    'target_value': float(target_value),
                    'future_value_current': float(fv_current),
                    'surplus': float(abs(remaining))  # Using abs() function explicitly
                }

            # PMT formula for monthly savings
            if monthly_return == 0:
                monthly_savings = remaining / months
            else:
                # Future value of annuity formula
                monthly_savings = (remaining * monthly_return) / ((1 + monthly_return) ** months - 1)

            total_savings = monthly_savings * months

            return {
                'monthly_savings_needed': float(monthly_savings),
                'total_savings_needed': float(total_savings),
                'current_value': float(current_value),
                'target_value': float(target_value),
                'future_value_current': float(fv_current),
                'gap': float(remaining)
            }

        except Exception as e:
            logger.error(f"Error in savings calculation: {e}")
            raise ValueError(f"Savings calculation failed: {str(e)}")

    @staticmethod
    def _calculate_retirement_needs(
            annual_expenses: float,
            years: int,
            inflation_rate: float,
            return_rate: float
    ) -> float:
        """Calculate total retirement needs considering inflation"""
        try:
            # Validate inputs
            if annual_expenses <= 0 or years <= 0:
                return annual_expenses * years

            # Real return rate
            if return_rate <= inflation_rate:
                # If real return is negative or zero, sum up inflated expenses
                total = sum(annual_expenses * (1 + inflation_rate) ** i for i in range(int(years)))
            else:
                # Present value of growing annuity
                real_return = (1 + return_rate) / (1 + inflation_rate) - 1

                if real_return <= 0:
                    total = annual_expenses * years * (1 + inflation_rate) ** (years / 2)
                else:
                    # Growing annuity formula
                    growth_factor = (1 + inflation_rate) / (1 + return_rate)
                    if abs(growth_factor - 1.0) < 1e-10:  # Avoid division by zero
                        total = annual_expenses * years
                    else:
                        total = annual_expenses * (1 - growth_factor ** years) / (1 - growth_factor)

            return max(total, annual_expenses * years)  # Ensure minimum reasonable value

        except Exception as e:
            logger.error(f"Error calculating retirement needs: {e}")
            # Fallback calculation
            return annual_expenses * years * (1 + inflation_rate) ** (years / 2)


# Additional utility functions that might be needed
def safe_divide(numerator, denominator, default=0.0):
    """Safely divide two numbers, returning default if denominator is zero"""
    try:
        if abs(denominator) < 1e-10:
            return default
        return numerator / denominator
    except (ZeroDivisionError, TypeError):
        return default


def safe_power(base, exponent, default=1.0):
    """Safely calculate power, handling edge cases"""
    try:
        if base <= 0 and exponent != int(exponent):
            return default
        return base ** exponent
    except (OverflowError, ValueError):
        return default


def format_currency_value(value):
    """Format currency values safely"""
    try:
        if abs(value) >= 10000000:  # 1 crore
            return f"₹{value/10000000:.1f}Cr"
        elif abs(value) >= 100000:  # 1 lakh
            return f"₹{value/100000:.1f}L"
        else:
            return f"₹{value:,.0f}"
    except (TypeError, ValueError):
        return "₹0"


def validate_positive_number(value, name="Value"):
    """Validate that a value is a positive number"""
    try:
        num_value = float(value)
        if num_value <= 0:
            raise ValueError(f"{name} must be positive, got {num_value}")
        return num_value
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid {name}: {e}")


def calculate_compound_growth(principal, rate, time):
    """Calculate compound growth safely"""
    try:
        return validate_positive_number(principal) * safe_power(1 + rate, time)
    except ValueError:
        return principal  # Return original if calculation fails
