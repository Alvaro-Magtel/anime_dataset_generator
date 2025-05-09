"""Main execution pipeline for genetic rule mining."""

from genetic_rule_miner.config import DBConfig
from genetic_rule_miner.data.database import DatabaseManager
from genetic_rule_miner.data.manager import DataManager
from genetic_rule_miner.data.preprocessing import (
    clean_string_columns,
    preprocess_data,
)
from genetic_rule_miner.models.genetic import GeneticRuleMiner
from genetic_rule_miner.utils.logging import LogManager

LogManager.configure()
logger = LogManager.get_logger(__name__)


def main() -> None:
    """Execute the complete rule mining pipeline."""
    try:
        logger.info("Starting rule mining pipeline")

        # Initialize components
        db_config = DBConfig()
        data_manager = DataManager(db_config)

        # Data loading and preparation
        logger.info("Loading and preprocessing data...")
        user_details, anime_data, user_scores = (
            data_manager.load_and_preprocess_data()
        )

        logger.info("Merging preprocessed data...")
        merged_data = DataManager.merge_data(
            user_scores, user_details, anime_data
        )

        # Genetic algorithm execution
        logger.info("Initializing genetic algorithm...")
        processed_df = preprocess_data(clean_string_columns(merged_data))
        # Filter to only 'high' ratings and drop the 'rating' column
        logger.info("Filtering data to include only 'high' ratings...")
        high_rating_data = processed_df[
            processed_df["rating"] == "high"
        ].copy()
        high_rating_data = high_rating_data.drop(columns=["rating"])

        miner = GeneticRuleMiner(
            df=processed_df,
            target="anime_id",
            user_cols=user_details.columns.tolist(),
            pop_size=1000,
            generations=10000,
        )
        logger.info("Starting evolution process..."),
        miner.evolve()

        # Output results
        high_fitness_rules = miner.get_high_fitness_rules(threshold=0.9)
        rules, ids = high_fitness_rules
        if high_fitness_rules:
            logger.info("\nRules with Fitness >= 0.9:")
            for idx, rule in enumerate(rules, start=1):
                formatted_rule = miner.format_rule(rule)
                fitness = miner.fitness(rule)
                logger.info(
                    f"Rule {idx}: {formatted_rule} (Fitness: {fitness:.4f})"
                )
        else:
            logger.info("No rules with Fitness >= 0.9 were found.")

        # Configuración de la base de datos
        db_manager = DatabaseManager(config=db_config)

        # Guardar las reglas en la tabla "rules"
        db_manager.save_rules(rules)

    except Exception as e:
        logger.error("Pipeline failed: %s", str(e), exc_info=True)
        raise


if __name__ == "__main__":
    main()
