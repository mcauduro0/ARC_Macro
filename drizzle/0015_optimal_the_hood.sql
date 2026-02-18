ALTER TABLE `portfolio_positions` MODIFY COLUMN `instrument` enum('fx','front','belly','long','hard','ntnb') NOT NULL;--> statement-breakpoint
ALTER TABLE `portfolio_trades` MODIFY COLUMN `instrument` enum('fx','front','belly','long','hard','ntnb') NOT NULL;--> statement-breakpoint
ALTER TABLE `portfolio_config` ADD `enableNtnb` boolean DEFAULT true NOT NULL;