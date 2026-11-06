SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;
ATTACH 'differential:lifecycle' AS main_raw (BRANCH 'main');
CREATE TABLE main_raw.transactions (
    transaction_id VARCHAR PRIMARY KEY,
    customer_id VARCHAR NOT NULL,
    transaction_date DATE NOT NULL,
    account_id VARCHAR NOT NULL,
    transaction_type VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    transaction_amount DECIMAL(18, 2) NOT NULL
);

            COPY main_raw.transactions FROM 'experiment/lifecycle/transactions.csv' (HEADER true);
        