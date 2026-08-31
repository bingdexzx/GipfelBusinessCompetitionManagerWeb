// ============================================================
// API 层类型定义 —— 与 server/prisma/schema.prisma 一一对应
// 每个模型导出：
//   Xxx            — 完整实体（Prisma 查询返回形态）
//   CreateXxxInput — 新建时的输入（去掉 id / createdAt / updatedAt 等自动生成字段）
//   UpdateXxxInput — 更新时的输入（CreateXxxInput 的 Partial，所有字段可选）
// ============================================================

// ===================== User =====================
export interface User {
  id: number;
  username: string;
  passwordHash: string;
  role: string; // SUPER_ADMIN | COMPETITION_ADMIN | PLAYER
  displayName: string | null;
  competitionId: number | null;
  permissions: string | null; // JSON array
  companyScopes: string | null; // JSON array
  viewCompanyScopes: string | null; // JSON array
  contractViewCompanyScopes: string | null; // JSON array
  stockCompanyScopes: string | null; // JSON array
  mustChangePassword: boolean;
  tokenVersion: number;
  createdAt: string;
  updatedAt: string;
}
export type CreateUserInput = Omit<User, 'id' | 'passwordHash' | 'tokenVersion' | 'createdAt' | 'updatedAt' | 'displayName' | 'competitionId' | 'permissions' | 'companyScopes' | 'viewCompanyScopes' | 'contractViewCompanyScopes' | 'stockCompanyScopes' | 'mustChangePassword'> & {
  password?: string;
  displayName?: string | null;
  competitionId?: number | null;
  permissions?: string | string[] | null;
  companyScopes?: string | number[] | null;
  viewCompanyScopes?: string | number[] | null;
  contractViewCompanyScopes?: string | number[] | null;
  stockCompanyScopes?: string | number[] | null;
  mustChangePassword?: boolean;
};
export type UpdateUserInput = Partial<Omit<CreateUserInput, 'username'>>;

// ===================== Competition =====================
export interface Competition {
  id: number;
  name: string;
  status: string; // ACTIVE | ARCHIVED
  mapBackground: string | null; // JSON { url, filename, width, height }
  stockConfig: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateCompetitionInput = Omit<Competition, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateCompetitionInput = Partial<CreateCompetitionInput>;

// ===================== FiscalYear =====================
export interface FiscalYear {
  id: number;
  competitionId: number;
  year: number;
  status: string; // ACTIVE | CLOSED
  createdAt: string;
  updatedAt: string;
}
export type CreateFiscalYearInput = Omit<FiscalYear, 'id' | 'createdAt' | 'updatedAt' | 'competitionId'> & {
  competitionId?: number | null;
};
export type UpdateFiscalYearInput = Partial<CreateFiscalYearInput>;

// ===================== Material =====================
export interface Material {
  id: number;
  name: string;
  origin: string;
  carbonEmissionCoefficient: number;
  nodePrices: string; // JSON: { [mapNodeId]: price }
  type: string; // NORMAL | SPECIAL
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateMaterialInput = Omit<Material, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateMaterialInput = Partial<CreateMaterialInput>;

// ===================== Part =====================
export interface Part {
  id: number;
  name: string;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreatePartInput = Omit<Part, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdatePartInput = Partial<CreatePartInput>;

// ===================== Product =====================
export interface Product {
  id: number;
  name: string;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateProductInput = Omit<Product, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateProductInput = Partial<CreateProductInput>;

// ===================== TechNode =====================
export interface TechNode {
  id: number;
  name: string;
  description: string | null;
  tier: number;
  researchCost: number;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateTechNodeInput = Omit<TechNode, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateTechNodeInput = Partial<CreateTechNodeInput>;

// ===================== MapNodeType =====================
export interface MapNodeType {
  id: number;
  name: string;
  description: string | null;
  color: string | null;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateMapNodeTypeInput = Omit<MapNodeType, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateMapNodeTypeInput = Partial<CreateMapNodeTypeInput>;

// ===================== PathType =====================
export interface PathType {
  id: number;
  name: string;
  description: string | null;
  color: string | null;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreatePathTypeInput = Omit<PathType, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdatePathTypeInput = Partial<CreatePathTypeInput>;

// ===================== MapNode =====================
export interface MapNode {
  id: number;
  name: string;
  region: string;
  nodeTypeId: number;
  x: number;
  y: number;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateMapNodeInput = Omit<MapNode, 'id' | 'createdAt' | 'updatedAt' | 'nodeTypeId'> & {
  nodeTypeId: number | null;
};
export type UpdateMapNodeInput = Partial<CreateMapNodeInput>;

// ===================== MapEdge =====================
export interface MapEdge {
  id: number;
  fromNodeId: number;
  toNodeId: number;
  distance: number;
  pathTypeId: number;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateMapEdgeInput = Omit<MapEdge, 'id' | 'createdAt' | 'updatedAt' | 'pathTypeId'> & {
  pathTypeId: number | null;
};
export type UpdateMapEdgeInput = Partial<CreateMapEdgeInput>;

// ===================== Infrastructure =====================
export interface Infrastructure {
  id: number;
  name: string;
  footprint: number;
  employmentRateBonus: number;
  populationBonus: number;
  highQualityPopulationBonus: number;
  price: number;
  happinessIndexBonus: number;
  perCapitaIncomeBonus: number;
  carbonReductionBonus: number;
  activationPrice: number;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateInfrastructureInput = Omit<Infrastructure, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateInfrastructureInput = Partial<CreateInfrastructureInput>;

// ===================== Warehouse =====================
export interface Warehouse {
  id: number;
  name: string;
  capacity: number;
  price: number;
  type: string; // MATERIAL | PART | PRODUCT
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateWarehouseInput = Omit<Warehouse, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateWarehouseInput = Partial<CreateWarehouseInput>;

// ===================== ProductionLine =====================
export interface ProductionLine {
  id: number;
  name: string;
  price: number;
  laborCount: number;
  maxPerYear: number;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateProductionLineInput = Omit<ProductionLine, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateProductionLineInput = Partial<CreateProductionLineInput>;

// ===================== Fuel =====================
export interface Fuel {
  id: number;
  name: string;
  pricePerLiter: number;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateFuelInput = Omit<Fuel, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateFuelInput = Partial<CreateFuelInput>;

// ===================== Vehicle =====================
export interface Vehicle {
  id: number;
  name: string;
  fuelId: number;
  fuelConsumptionPerKm: number;
  maxCargo: number;
  price: number;
  carbonEmission: number;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateVehicleInput = Omit<Vehicle, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateVehicleInput = Partial<CreateVehicleInput>;

// ===================== Region =====================
export interface Region {
  id: number;
  name: string;
  description: string | null;
  competitionId: number | null;
  overviewCards: string; // JSON array
  createdAt: string;
  updatedAt: string;
}
export type CreateRegionInput = Omit<Region, 'id' | 'createdAt' | 'updatedAt' | 'overviewCards'> & {
  overviewCards?: string;
};
export type UpdateRegionInput = Partial<CreateRegionInput>;

// ===================== ConsumerDemand =====================
export interface ConsumerDemand {
  id: number;
  competitionId: number | null;
  region: string;
  productId: number | null;
  productType: string;
  quantity: number;
  note: string | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateConsumerDemandInput = Omit<ConsumerDemand, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateConsumerDemandInput = Partial<CreateConsumerDemandInput>;

// ===================== Company =====================
export interface Company {
  id: number;
  name: string;
  industryTypeId: number | null;
  competitionId: number | null;
  status: string; // ACTIVE | ...
  regionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateCompanyInput = Omit<Company, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateCompanyInput = Partial<CreateCompanyInput>;

// ===================== CompanyFieldValue =====================
export interface CompanyFieldValue {
  id: number;
  companyId: number;
  industryFieldId: number;
  value: string;
  version: number;
  updatedAt: string;
}
export type CreateCompanyFieldValueInput = Omit<CompanyFieldValue, 'id' | 'version' | 'updatedAt'>;
export type UpdateCompanyFieldValueInput = Partial<CreateCompanyFieldValueInput>;

// ===================== IndustryType =====================
export interface IndustryType {
  id: number;
  name: string;
  code: number;
  description: string | null;
  icon: string | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateIndustryTypeInput = Omit<IndustryType, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateIndustryTypeInput = Partial<CreateIndustryTypeInput>;

// ===================== IndustryField =====================
export interface IndustryField {
  id: number;
  industryTypeId: number;
  name: string;
  fieldKey: string;
  fieldType: string; // STRING | NUMBER | BOOLEAN | DICTIONARY | LIST
  config: string; // JSON
  defaultValue: string | null;
  isCalculated: boolean;
  calcGraph: string | null; // JSON
  formula: string | null;
  sortOrder: number;
  visible: boolean;
  timerEnabled: boolean;
  timerTrigger: string | null; // FY_START | FY_END
  timerValue: string | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateIndustryFieldInput = Omit<IndustryField, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateIndustryFieldInput = Partial<CreateIndustryFieldInput>;

// ===================== ContractType =====================
export interface ContractType {
  id: number;
  key: string;
  name: string;
  description: string | null;
  partyCount: number;
  partyRoles: string; // JSON
  inputSchema: string; // JSON
  effects: string; // JSON
  conditions: string; // JSON
  graph: string | null; // JSON
  schemaVersion: number;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}
export type CreateContractTypeInput = Omit<ContractType, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateContractTypeInput = Partial<CreateContractTypeInput>;

// ===================== Contract =====================
export interface Contract {
  id: number;
  competitionId: number;
  contractTypeId: number;
  name: string;
  status: string; // DRAFT | PENDING_EXEC | EXECUTED | TERMINATED
  parties: string; // JSON
  inputs: string; // JSON
  executionLog: string | null; // JSON
  executionResult: string | null; // JSON
  signedAt: string | null;
  executedAt: string | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateContractInput = Omit<Contract, 'id' | 'executionLog' | 'executionResult' | 'signedAt' | 'executedAt' | 'createdAt' | 'updatedAt' | 'competitionId' | 'inputs' | 'parties' | 'name' | 'status'> & {
  competitionId?: number | null;
  name?: string;
  status?: string;
  parties: string | Record<string, any>[];
  inputs: string | Record<string, any>;
};
export type UpdateContractInput = Partial<CreateContractInput>;

// ===================== ContractFieldEffect =====================
export interface ContractFieldEffect {
  id: number;
  contractId: number;
  companyId: number;
  industryFieldId: number;
  fieldKey: string;
  fieldName: string;
  op: string; // ADD | SUB | SET
  valueRaw: string; // JSON
  beforeRaw: string; // JSON
  afterRaw: string; // JSON
  createdAt: string;
}

// ===================== Message =====================
export interface Message {
  id: number;
  title: string;
  content: string;
  senderId: number;
  competitionId: number | null;
  targetsAll: boolean;
  targetUserIds: string; // JSON array
  images: string | null; // JSON array
  createdAt: string;
  updatedAt: string;
}
export type CreateMessageInput = Omit<Message, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateMessageInput = Partial<CreateMessageInput>;

// ===================== MessageRecipient =====================
export interface MessageRecipient {
  id: number;
  messageId: number;
  userId: number;
  read: boolean;
  readAt: string | null;
  createdAt: string;
}

// ===================== Stock =====================
export interface Stock {
  id: number;
  code: string;
  name: string;
  totalShares: number;
  initNetProfit: number;
  industryPE: number;
  currentCarbon: number;
  industryAvgCarbon: number;
  happiness: number;
  carbonFieldRef: string | null; // JSON { region, cardId }
  happinessFieldRef: string | null; // JSON { region, cardId }
  industryAvgCarbonRefs: string | null; // JSON array
  pbCompanyId: number | null;
  pbFieldId: number | null;
  pbRandom: number | null;
  initPrice: number;
  currentPrice: number;
  round: number;
  companyId: number | null;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateStockInput = Omit<Stock, 'id' | 'initPrice' | 'currentPrice' | 'round' | 'createdAt' | 'updatedAt' | 'industryPE' | 'pbRandom'> & {
  industryPE?: number;
  pbRandom?: number | null;
};
export type UpdateStockInput = Partial<CreateStockInput>;

// ===================== StockFundsAccount =====================
export interface StockFundsAccount {
  id: number;
  name: string;
  ownerType: string; // COMPANY | USER
  companyId: number | null;
  userId: number | null;
  cashBalance: number;
  bindFieldId: number | null;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateStockFundsAccountInput = Omit<StockFundsAccount, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateStockFundsAccountInput = Partial<CreateStockFundsAccountInput>;

// ===================== StockHolding =====================
export interface StockHolding {
  id: number;
  fundsAccountId: number;
  stockId: number;
  shares: number;
  costPrice: number;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateStockHoldingInput = Omit<StockHolding, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateStockHoldingInput = Partial<CreateStockHoldingInput>;

// ===================== StockOrder =====================
export interface StockOrder {
  id: number;
  stockId: number;
  fundsAccountId: number;
  side: string; // BUY | SELL
  price: number;
  quantity: number;
  amount: number;
  status: string; // PENDING | FILLED | CANCELLED
  round: number;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}
export type CreateStockOrderInput = Omit<StockOrder, 'id' | 'amount' | 'status' | 'round' | 'createdAt' | 'updatedAt' | 'competitionId'> & {
  competitionId?: number | null;
};
export type UpdateStockOrderInput = Partial<CreateStockOrderInput>;

// ===================== StockCandle =====================
export interface StockCandle {
  id: number;
  stockId: number;
  round: number;
  open: number;
  high: number;
  low: number;
  close: number;
  changePct: number;
  competitionId: number | null;
  createdAt: string;
  updatedAt: string;
}

// ===================== AuditLog =====================
export interface AuditLog {
  id: number;
  kind: string; // write | error
  operatorId: number | null;
  operatorName: string | null;
  action: string;
  model: string | null;
  recordId: string | null;
  competitionId: number | null;
  changes: string | null; // JSON
  statusCode: number | null;
  errorSummary: string | null;
  ip: string | null;
  requestId: string | null;
  createdAt: string;
}

// ===================== 通用查询参数 =====================
export interface PaginationParams {
  page?: number;
  pageSize?: number;
}

export interface PagedResult<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export interface IncrementalResult<T> {
  incremental: true;
  items: T[];
  serverTime: string;
  existingIds?: number[];
}
