// TypeScript config module
export interface Config {
    port: number;
    host: string;
}

export const defaultConfig: Config = {
    port: 3000,
    host: "localhost",
};
