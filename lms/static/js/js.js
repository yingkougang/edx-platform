//<![CDATA[
$(function(){
	(function(){
		var curr = 0;
		$(".home .content .area .js #jsNav .trigger").each(function(i){
			$(this).click(function(){
				curr = i;
				$(".home .content .area #js img").eq(i).fadeIn("slow").siblings("img").hide();
				$(this).siblings(".trigger").removeClass("imgSelected").end().addClass("imgSelected");
				return false;
			});
		});
		
		var pg = function(flag){
			if (flag) {
                todo = (curr - 1) % 4;
                /*
				if (curr == 0) {
					todo = 2;
				} else {
					todo = (curr - 1) % 4;
				}
				*/
			} else {
				todo = (curr + 1) % 4;
			}
			$(".home .content .area .js #jsNav .trigger").eq(todo).click();
		};
		
		//ǰ
		$(".home .content .area #prev").click(function(){
			pg(true);
			return false;
		});
		
		//
		$(".home .content .area #next").click(function(){
			pg(false);
			return false;
		});
		
		//Զ
		var timer = setInterval(function(){
			todo = (curr + 1) % 4;
			$(".home .content .area .js #jsNav .trigger").eq(todo).click();
		},3000);
		
		$(".home .content .area #js,.home .content .area #prev,.home .content .area #next").hover(function(){
				clearInterval(timer);
			},
			function(){
				timer = setInterval(function(){
					todo = (curr + 1) % 4;
					$(".home .content .area .js #jsNav .trigger").eq(todo).click();
				},3000);			
			}
		);
	})();
});
//]]>

