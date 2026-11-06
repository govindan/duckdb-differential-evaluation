CREATE TABLE main_raw.transactions (
    transaction_id VARCHAR PRIMARY KEY,
    customer_id VARCHAR NOT NULL,
    transaction_date DATE NOT NULL,
    account_id VARCHAR NOT NULL,
    transaction_type VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    transaction_amount DECIMAL(18, 2) NOT NULL
);
