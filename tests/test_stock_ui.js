// 测试股票管理界面的涨跌幅显示
console.log('测试股票管理界面的涨跌幅显示功能');

// 模拟股票数据
const mockStocks = [
  {
    id: 1,
    code: '600001',
    name: '测试股票A',
    currentPrice: 105.50,
    initPrice: 100.00,
    changePct: 5.50,
    changePrice: 5.50
  },
  {
    id: 2,
    code: '600002', 
    name: '测试股票B',
    currentPrice: 95.20,
    initPrice: 100.00,
    changePct: -4.80,
    changePrice: -4.80
  },
  {
    id: 3,
    code: '600003',
    name: '测试股票C',
    currentPrice: 100.00,
    initPrice: 100.00,
    changePct: 0,
    changePrice: 0
  }
];

// 测试样式类函数
function getPriceChangeClass(stock) {
  if (stock.changePct === undefined || stock.changePct === 0) {
    // 如果没有涨跌幅信息，使用当前价与初始价比较
    return Number(stock.currentPrice) >= Number(stock.initPrice) ? 'up' : 'down';
  }
  return stock.changePct >= 0 ? 'up' : 'down';
}

// 测试每个股票
mockStocks.forEach(stock => {
  const cssClass = getPriceChangeClass(stock);
  console.log(`股票 ${stock.name}:`);
  console.log(`  当前价: ${stock.currentPrice}, 初始价: ${stock.initPrice}`);
  console.log(`  涨跌幅: ${stock.changePct}%`);
  console.log(`  CSS类: ${cssClass}`);
  console.log(`  预期颜色: ${cssClass === 'up' ? '红色(涨)' : '绿色(跌)'}`);
  console.log('---');
});

// 测试边界情况
console.log('\n测试边界情况:');
const edgeCases = [
  { currentPrice: 100, initPrice: 100, changePct: undefined }, // 无涨跌幅信息
  { currentPrice: 100, initPrice: 100, changePct: 0 },        // 涨跌幅为0
  { currentPrice: 100.001, initPrice: 100, changePct: 0.001 }, // 微小涨幅
  { currentPrice: 99.999, initPrice: 100, changePct: -0.001 }  // 微小跌幅
];

edgeCases.forEach((stock, index) => {
  const cssClass = getPriceChangeClass(stock);
  console.log(`边界情况 ${index + 1}: ${cssClass}`);
});

console.log('\n✅ 测试完成');